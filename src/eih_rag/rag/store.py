"""Adaptateur Chroma persistant et independant de la couche HTTP."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal
from uuid import uuid4

from chromadb.errors import NotFoundError

from ..models import Chunk
from .embeddings import Embedder


logger = logging.getLogger(__name__)


class StoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    chunk_id: str
    text: str
    file: str
    reference: str | None
    date: str | None
    page: int
    section: str | None
    score: float
    title: str | None = None
    section_path: str | None = None
    document_type: str | None = None
    # Score absolu dans [0, 1] utilise pour le seuil de refus (cosinus ou reranker).
    relevance: float | None = None
    origin: Literal["official", "upload"] = "official"


class ChromaStore:
    """Base vectorielle Chroma stockee dans ``data/chroma``."""

    def __init__(
        self, directory: Path, collection_name: str, embedder: Embedder, manifest_path: Path | None = None
    ) -> None:
        self.directory = Path(directory)
        self.collection_name = collection_name
        self.embedder = embedder
        self.manifest_path = manifest_path or self.directory / f"{collection_name}.json"
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import chromadb
                self.directory.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=str(self.directory))
            except Exception as error:  # pragma: no cover - depends on machine configuration
                raise StoreUnavailable(f"Base Chroma indisponible : {error}") from error
        return self._client

    @property
    def version(self) -> str:
        # Le nom de la collection change a chaque publication et invalide le cache BM25.
        return read_index_manifest(self.manifest_path).get("collection") or self.collection_name

    @property
    def collection(self):
        try:
            name = self.version
            if name != self.collection_name:
                return self.client.get_collection(name=name, embedding_function=None)
            return self.client.get_or_create_collection(
                name=name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine"},
            )
        except StoreUnavailable:
            raise
        except Exception as error:  # pragma: no cover - Chroma boundary
            raise StoreUnavailable(f"Collection Chroma indisponible : {error}") from error

    def count(self) -> int:
        try:
            return self.collection.count()
        except Exception as error:  # pragma: no cover - defensive boundary
            raise StoreUnavailable(f"Impossible de lire Chroma : {error}") from error

    @staticmethod
    def _metadata(chunk: Chunk) -> dict[str, str | int | float | bool]:
        return {
            "chunk_id": chunk.chunk_id,
            "file": chunk.file,
            "reference": chunk.reference or "",
            "document_type": chunk.document_type or "",
            "date": chunk.published_date or "",
            "published_at": chunk.published_at or "",
            "version": chunk.version or "",
            "status": chunk.status or "",
            "page": chunk.page,
            "section": chunk.section or "",
            "section_path": chunk.section_path or "",
            "title": chunk.title or "",
            "strategy": chunk.strategy,
            "origin": chunk.origin,
        }

    def _discard_collection(self, name: str) -> None:
        try:
            self.client.delete_collection(name)
        except NotFoundError:
            pass
        except Exception:
            logger.warning("Impossible de nettoyer la collection Chroma %s", name, exc_info=True)

    @contextmanager
    def stage_rebuild(self, chunks: list[Chunk]) -> Iterator[str]:
        """Prepare une collection inactive, puis laisse l'appelant publier son manifeste."""
        previous = self.version
        name = f"{self.collection_name[:30]}_{uuid4().hex}"
        client = self.client
        try:
            collection = client.create_collection(
                name=name, embedding_function=None, metadata={"hnsw:space": "cosine"}
            )
            for offset in range(0, len(chunks), 64):
                batch = chunks[offset : offset + 64]
                collection.upsert(
                    ids=[chunk.id for chunk in batch],
                    documents=[chunk.text for chunk in batch],
                    metadatas=[self._metadata(chunk) for chunk in batch],
                    embeddings=self.embedder.embed_documents([chunk.index_text for chunk in batch]),
                )
        except Exception as error:
            self._discard_collection(name)
            raise StoreUnavailable(f"Echec de l'indexation Chroma : {error}") from error

        try:
            yield name
        except BaseException:
            self._discard_collection(name)
            raise
        else:
            self._discard_collection(previous)

    def rebuild(self, chunks: list[Chunk]) -> None:
        """Remplace l'index entier, y compris pour les appels hors service."""
        with self.stage_rebuild(chunks) as name:
            write_manifest(self.manifest_path, [], {}, name)

    @staticmethod
    def _to_chunk(item_id: str, text: str, metadata: dict | None, score: float) -> RetrievedChunk:
        metadata = metadata or {}
        return RetrievedChunk(
            id=item_id,
            chunk_id=str(metadata.get("chunk_id", "")),
            text=text,
            file=str(metadata.get("file", "")),
            reference=str(metadata.get("reference") or "") or None,
            date=str(metadata.get("date") or "") or None,
            page=int(metadata.get("page", 0)),
            section=str(metadata.get("section") or "") or None,
            score=score,
            title=str(metadata.get("title") or "") or None,
            section_path=str(metadata.get("section_path") or "") or None,
            document_type=str(metadata.get("document_type") or "") or None,
            relevance=score,
            origin="upload" if metadata.get("origin") == "upload" else "official",
        )

    def all_chunks(self) -> tuple[list[RetrievedChunk], list[list[float]]]:
        """Tous les fragments et leurs embeddings (corpus BM25 + scores denses)."""
        try:
            data = self.collection.get(include=["documents", "metadatas", "embeddings"])
        except Exception as error:  # pragma: no cover - Chroma boundary
            raise StoreUnavailable(f"Lecture Chroma impossible : {error}") from error
        ids = data.get("ids") or []
        embeddings = data.get("embeddings")
        embeddings = [] if embeddings is None else [list(vector) for vector in embeddings]
        chunks = [self._to_chunk(i, t, m, 0.0) for i, t, m in zip(ids, data.get("documents") or [], data.get("metadatas") or [])]
        order = sorted(range(len(chunks)), key=lambda index: chunks[index].id)
        return [chunks[i] for i in order], [embeddings[i] for i in order] if embeddings else []

    def search(self, question: str, top_k: int, document_type: str | None = None) -> list[RetrievedChunk]:
        if self.count() == 0:
            return []
        where = {"document_type": {"$eq": document_type}} if document_type else None
        try:
            results = self.collection.query(
                query_embeddings=[self.embedder.embed_query(question)],
                n_results=min(top_k, self.count()),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as error:  # pragma: no cover - Chroma / model boundary
            raise StoreUnavailable(f"Echec de la recherche Chroma : {error}") from error

        documents = results.get("documents", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        ids = results.get("ids", [[]])[0] or []
        hits = [
            self._to_chunk(item_id, text, metadata, round(1.0 - float(distance), 4))
            for item_id, text, metadata, distance in zip(ids, documents, metadatas, distances, strict=True)
        ]
        return hits


def write_manifest(
    path: Path, documents: list[dict[str, Any]], strategy: dict[str, Any], collection: str
) -> None:
    """Publie ensemble le catalogue et le nom de la collection active."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(
                {"documents": documents, "strategy": strategy, "collection": collection},
                stream, ensure_ascii=False, indent=2,
            )
        temporary.replace(path)
    except OSError as error:
        raise StoreUnavailable(f"Impossible de publier le manifeste : {error}") from error
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def read_index_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Un objet JSON est attendu.")
        return payload
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise StoreUnavailable(f"Manifeste d'index illisible : {error}") from error
