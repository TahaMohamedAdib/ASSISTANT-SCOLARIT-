"""Orchestration ingestion -> Chroma -> recherche -> generation citee."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from ..chunking import create_chunks
from ..config import Settings
from ..extraction import extract_pdf
from ..schemas import AskRequest, AskResponse, IngestRequest, IngestResponse, SearchRequest, Source
from .embeddings import build_embedder
from .llm import AnswerGenerator, build_generator
from .retrieval import CrossEncoderReranker, HybridRetriever, LLMQueryRewriter, RetrievalConfig
from .prompting import NO_ANSWER, SYSTEM_PROMPT, build_user_prompt, invalid_citations, is_refusal, normalize_citations
from .store import ChromaStore, RetrievedChunk, read_manifest, write_manifest


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
        self.store = store or ChromaStore(settings.chroma_dir, settings.collection_name, build_embedder(settings.embedding_backend, settings.embedding_model))
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
            excerpt=chunk.text,
            score=chunk.relevance if chunk.relevance is not None else chunk.score,
            title=chunk.title,
            document_id=chunk.document_id,
            document_type=chunk.document_type,
            section=chunk.section_path or chunk.section,
            methods=list(chunk.methods),
        )

    def ingest(self, request: IngestRequest) -> IngestResponse:
        pdf_files = sorted(self.settings.corpus_dir.glob("*.pdf"))
        if len(pdf_files) != 7:
            raise ValueError(f"Le corpus doit contenir exactement 7 PDF (trouve : {len(pdf_files)}).")

        documents = []
        all_chunks = []
        for pdf_path in pdf_files:
            metadata, pages = extract_pdf(pdf_path)
            chunks = create_chunks(pages, metadata, request.strategy, request.chunk_size, request.overlap)
            document = metadata.to_dict()
            document["chunk_count"] = len(chunks)
            documents.append(document)
            all_chunks.extend(chunks)
        self.store.rebuild(all_chunks)
        write_manifest(
            self.settings.manifest_path,
            documents,
            {"strategy": request.strategy, "chunk_size": request.chunk_size, "overlap": request.overlap},
        )
        return IngestResponse(
            documents_indexed=len(documents),
            chunks_indexed=len(all_chunks),
            strategy=request.model_copy(),
        )

    def documents(self) -> list[dict]:
        return read_manifest(self.settings.manifest_path)

    def search_hits(self, question: str, top_k: int, document_type: str | None) -> list[RetrievedChunk]:
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

        answer = self.generator.generate(SYSTEM_PROMPT, build_user_prompt(request.question, hits)).strip()
        answer = normalize_citations(answer)
        refused = is_refusal(answer)
        return AskResponse(
            answer=NO_ANSWER if refused else answer,
            found=not refused,
            sources=sources,
            invalid_citations=invalid_citations(answer, len(sources)),
            latency_ms=round((perf_counter() - started_at) * 1000),
        )
