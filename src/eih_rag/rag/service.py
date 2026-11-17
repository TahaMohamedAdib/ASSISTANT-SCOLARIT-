"""Orchestration ingestion -> Chroma -> recherche -> generation citee."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory, mkdtemp
from time import perf_counter
from typing import Any, BinaryIO, Literal

from filelock import FileLock

from ..chunking import create_chunks
from ..config import Settings
from ..extraction import extract_pdf
from ..models import Chunk
from ..schemas import AskRequest, AskResponse, IndexedDocument, IngestRequest, IngestResponse, SearchRequest, Source
from .embeddings import build_embedder
from .llm import AnswerGenerator, build_generator
from .prompting import NO_ANSWER, SYSTEM_PROMPT, SYSTEM_PROMPT_V2, build_user_prompt, invalid_citations, is_refusal
from .retrieval import CrossEncoderReranker, HybridRetriever, LLMQueryRewriter, RetrievalConfig
from .store import ChromaStore, RetrievedChunk, StoreUnavailable, read_index_manifest, write_manifest


logger = logging.getLogger(__name__)
DocumentOrigin = Literal["official", "upload"]


class DocumentError(ValueError):
    pass


class InvalidDocumentName(DocumentError):
    pass


class UnsupportedDocument(DocumentError):
    pass


class DocumentTooLarge(DocumentError):
    pass


class DocumentConflict(DocumentError):
    pass


class OfficialDocument(DocumentError):
    pass


class DocumentNotFound(DocumentError):
    pass


def _name_key(filename: str) -> str:
    return unicodedata.normalize("NFC", filename).casefold()


def _validate_filename(filename: str) -> None:
    if (
        not re.fullmatch(r"[\w(][\w .()'-]*", unicodedata.normalize("NFC", filename))
        or len(filename.encode("utf-8")) > 255
        or PureWindowsPath(filename).is_reserved()
    ):
        raise InvalidDocumentName("Nom de fichier invalide.")
    if Path(filename).suffix.lower() != ".pdf":
        raise UnsupportedDocument("Seuls les fichiers PDF sont acceptes.")



@dataclass(frozen=True)
class SearchResult:
    fragments: list[Source]


class RagService:
    def __init__(
        self,
        settings: Settings,
        store: ChromaStore | None = None,
        generator: AnswerGenerator | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or ChromaStore(
            settings.chroma_dir, settings.collection_name,
            build_embedder(settings.embedding_backend, settings.embedding_model),
            manifest_path=settings.manifest_path,
        )
        if isinstance(self.store, ChromaStore):
            self.store.manifest_path = settings.manifest_path
        self._index_lock = FileLock(str(settings.manifest_path.resolve()) + ".lock")
        self.generator = generator or build_generator(
            settings.llm_provider,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            openai_base_url=settings.openai_base_url,
            openai_model=settings.openai_model,
            openai_api_key=settings.openai_api_key,
        )
        # Sans methode ``all_chunks`` (store de test), on reste en recherche dense simple.
        if retriever is None and hasattr(self.store, "all_chunks"):
            retriever = HybridRetriever(
                self.store,
                RetrievalConfig(
                    mode=settings.retrieval_mode,
                    dense_weight=settings.hybrid_dense_weight,
                    candidate_k=settings.candidate_k,
                    rerank=settings.reranker_enabled,
                    rerank_candidates=settings.rerank_candidates,
                    query_expansion=settings.query_expansion,
                ),
                reranker=CrossEncoderReranker(settings.reranker_model) if settings.reranker_enabled else None,
                rewriter=LLMQueryRewriter(self.generator) if settings.query_expansion else None,
            )
        self.retriever = retriever

    @staticmethod
    def _source(chunk: RetrievedChunk) -> Source:
        return Source(
            id=chunk.id,
            chunk_id=chunk.chunk_id,
            file=chunk.file,
            reference=chunk.reference,
            date=chunk.date,
            page=chunk.page,
            section=chunk.section,
            excerpt=chunk.text,
            score=chunk.relevance if chunk.relevance is not None else chunk.score,
        )

    @contextmanager
    def _locked_index(self) -> Iterator[None]:
        try:
            with self._index_lock:
                yield
        except OSError as error:
            raise StoreUnavailable(f"Acces aux fichiers de l'index impossible : {error}") from error

    @staticmethod
    def _pdf_files(directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(
            path for path in directory.iterdir()
            if path.suffix.lower() == ".pdf" and not path.is_symlink() and path.is_file()
        )

    def _pdf_directories(self) -> tuple[Path, Path]:
        corpus = self.settings.corpus_dir.resolve()
        uploads = self.settings.uploads_dir.resolve()
        if uploads.is_relative_to(corpus) or corpus.is_relative_to(uploads):
            raise StoreUnavailable("Les dossiers du corpus officiel et des televersements doivent etre distincts.")
        return corpus, uploads

    def _current_strategy(self) -> IngestRequest:
        strategy = read_index_manifest(self.settings.manifest_path).get("strategy", {})
        try:
            return IngestRequest.model_validate(strategy)
        except ValueError as error:
            raise StoreUnavailable("Strategie de decoupage invalide dans le manifeste.") from error

    def _build_index(
        self,
        official: list[Path],
        uploads: list[Path],
        request: IngestRequest,
        new_upload: Path | None = None,
    ) -> tuple[list[dict[str, Any]], list[Chunk]]:
        sources: list[tuple[Path, DocumentOrigin]] = [(path, "official") for path in official]
        sources.extend((path, "upload") for path in uploads)
        documents = []
        all_chunks = []
        seen_names = set()
        for path, origin in sources:
            key = _name_key(path.name)
            if key in seen_names:
                raise StoreUnavailable(f"Nom de PDF utilise plusieurs fois : {path.name}.")
            seen_names.add(key)
            try:
                metadata, pages = extract_pdf(path)
            except OSError:
                raise
            except Exception as error:
                if path == new_upload:
                    raise UnsupportedDocument("Le fichier PDF est illisible ou protege.") from error
                raise StoreUnavailable(f"Extraction impossible pour le PDF {path.name}.") from error
            chunks = create_chunks(pages, metadata, request.strategy, request.chunk_size, request.overlap)
            if origin == "upload":
                if not chunks:
                    if path == new_upload:
                        raise UnsupportedDocument("Le PDF ne contient aucun texte indexable.")
                    raise StoreUnavailable(f"Aucun texte indexable dans le PDF {path.name}.")
                chunks = [replace(chunk, id=f"upload:{path.name}:{chunk.id}", origin=origin) for chunk in chunks]
            document = metadata.to_dict()
            document.update(chunk_count=len(chunks), origin=origin)
            documents.append(document)
            all_chunks.extend(chunks)
        return documents, all_chunks

    def _publish_manifest(self, documents: list[dict[str, Any]], request: IngestRequest, collection: str) -> None:
        write_manifest(self.settings.manifest_path, documents, request.model_dump(), collection)

    def ingest(self, request: IngestRequest) -> IngestResponse:
        with self._locked_index():
            corpus, uploads = self._pdf_directories()
            documents, chunks = self._build_index(self._pdf_files(corpus), self._pdf_files(uploads), request)
            with self.store.stage_rebuild(chunks) as collection:
                self._publish_manifest(documents, request, collection)
            return IngestResponse(documents_indexed=len(documents), chunks_indexed=len(chunks), strategy=request)

    def _save_pdf(self, stream: BinaryIO, destination: Path) -> None:
        limit = self.settings.max_upload_bytes
        header = stream.read(min(1024, limit + 1))
        if len(header) > limit:
            raise DocumentTooLarge(f"Le fichier depasse la limite de {limit} octets.")
        if not header.startswith(b"%PDF-"):
            raise UnsupportedDocument("Le contenu du fichier doit etre un PDF.")
        size = len(header)
        with destination.open("xb") as output:
            output.write(header)
            while block := stream.read(min(64 * 1024, limit - size + 1)):
                size += len(block)
                if size > limit:
                    raise DocumentTooLarge(f"Le fichier depasse la limite de {limit} octets.")
                output.write(block)

    def upload_document(self, filename: str, stream: BinaryIO) -> IndexedDocument:
        _validate_filename(filename)
        with self._locked_index():
            corpus, uploads = self._pdf_directories()
            official = self._pdf_files(corpus)
            uploads.mkdir(parents=True, exist_ok=True)
            existing = self._pdf_files(uploads)
            if any(_name_key(path.name) == _name_key(filename) for path in [*official, *uploads.iterdir()]):
                raise DocumentConflict("Un document porte deja ce nom.")
            request = self._current_strategy()
            with TemporaryDirectory(dir=uploads, ignore_cleanup_errors=True) as directory:
                pending = Path(directory) / filename
                self._save_pdf(stream, pending)
                documents, chunks = self._build_index(official, [*existing, pending], request, new_upload=pending)
                result = IndexedDocument.model_validate(documents[-1])
                destination = uploads / filename
                with self.store.stage_rebuild(chunks) as collection:
                    pending.replace(destination)
                    try:
                        self._publish_manifest(documents, request, collection)
                    except BaseException:
                        destination.unlink()
                        raise
                return result

    def delete_document(self, filename: str) -> None:
        _validate_filename(filename)
        with self._locked_index():
            corpus, uploads = self._pdf_directories()
            official = self._pdf_files(corpus)
            if any(_name_key(path.name) == _name_key(filename) for path in official):
                raise OfficialDocument("Un document officiel ne peut pas etre supprime.")
            existing = self._pdf_files(uploads)
            target = next((path for path in existing if _name_key(path.name) == _name_key(filename)), None)
            if target is None:
                raise DocumentNotFound("Document televerse introuvable.")
            request = self._current_strategy()
            documents, chunks = self._build_index(official, [path for path in existing if path != target], request)
            with self.store.stage_rebuild(chunks) as collection:
                # Le PDF reste recuperable jusqu'a la publication du manifeste.
                staging = Path(mkdtemp(dir=uploads))
                pending = staging / target.name
                try:
                    target.replace(pending)
                    try:
                        self._publish_manifest(documents, request, collection)
                    except BaseException:
                        pending.replace(target)
                        raise
                finally:
                    # Si la restauration echoue, conserver la copie de secours.
                    if not pending.exists():
                        staging.rmdir()
            try:
                pending.unlink()
                staging.rmdir()
            except OSError:
                logger.warning("Impossible de nettoyer le PDF supprime %s", pending, exc_info=True)

    def documents(self) -> list[IndexedDocument]:
        with self._locked_index():
            documents = read_index_manifest(self.settings.manifest_path).get("documents", [])
            try:
                return [IndexedDocument.model_validate(document) for document in documents]
            except (TypeError, ValueError) as error:
                raise StoreUnavailable("Catalogue de documents invalide dans le manifeste.") from error

    def indexed_chunk_count(self) -> int:
        with self._locked_index():
            return self.store.count()

    def search_hits(self, question: str, top_k: int, document_type: str | None) -> list[RetrievedChunk]:
        with self._locked_index():
            if self.retriever is not None:
                return self.retriever.search(question, top_k, document_type)
            return self.store.search(question, top_k, document_type)

    def search(self, request: SearchRequest) -> SearchResult:
        hits = self.search_hits(request.question, request.top_k, request.filters.type)
        return SearchResult(fragments=[self._source(hit) for hit in hits])

    def ask(self, request: AskRequest) -> AskResponse:
        started_at = perf_counter()
        hits = self.search_hits(request.question, request.top_k, request.filters.type)
        sources = [self._source(hit) for hit in hits]
        best = max((hit.relevance if hit.relevance is not None else hit.score) for hit in hits) if hits else None
        if best is None or best < self.settings.score_threshold:
            return AskResponse(
                answer=NO_ANSWER,
                found=False,
                sources=[],
                invalid_citations=[],
                latency_ms=round((perf_counter() - started_at) * 1000),
            )

        prompt = SYSTEM_PROMPT if any(hit.origin == "upload" for hit in hits) else SYSTEM_PROMPT_V2
        answer = self.generator.generate(prompt, build_user_prompt(request.question, hits)).strip()
        refused = is_refusal(answer)
        return AskResponse(
            answer=NO_ANSWER if refused else answer,
            found=not refused,
            sources=sources,
            invalid_citations=invalid_citations(answer, len(sources)),
            latency_ms=round((perf_counter() - started_at) * 1000),
        )
