"""Adaptateur Chroma persistant et independant de la couche HTTP."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chromadb.errors import NotFoundError

from ..models import Chunk
from .embeddings import Embedder


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
    document_id: str | None = None
    # Methodes ayant trouve le fragment : "dense", "bm25", "rerank" (mode transparence).
    methods: tuple[str, ...] = ()


class ChromaStore:
    """Base vectorielle Chroma stockee dans ``data/chroma``."""

    def __init__(self, directory: Path, collection_name: str, embedder: Embedder) -> None:
        self.directory = Path(directory)
        self.collection_name = collection_name
        self.embedder = embedder
        self._client = None
        self._collection = None
        # Incremente a chaque reconstruction : invalide le cache BM25 du retriever.
        self.version = 0

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
    def collection(self):
        if self._collection is None:
            try:
                self._collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=None,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as error:  # pragma: no cover - defensive boundary
                raise StoreUnavailable(f"Collection Chroma indisponible : {error}") from error
        return self._collection

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
            "document_id": chunk.document_id or "",
            "strategy": chunk.strategy,
        }

    def rebuild(self, chunks: list[Chunk]) -> None:
        """Remplace l'index entier : relancer l'ingestion ne cree aucun doublon."""
        try:
            try:
                self.client.delete_collection(self.collection_name)
            except (ValueError, NotFoundError):
                pass
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine"},
            )
            self._upsert(chunks)
        except StoreUnavailable:
            raise
        except Exception as error:  # pragma: no cover - Chroma / model boundary
            raise StoreUnavailable(f"Echec de l'indexation Chroma : {error}") from error
        self.version += 1

    def _upsert(self, chunks: list[Chunk], progress=None) -> None:
        for offset in range(0, len(chunks), 32):
            batch = chunks[offset : offset + 32]
            self.collection.upsert(
                ids=[chunk.id for chunk in batch],
                documents=[chunk.text for chunk in batch],
                metadatas=[self._metadata(chunk) for chunk in batch],
                # On indexe le texte enrichi (titre + hierarchie) mais on stocke le texte brut.
                embeddings=self.embedder.embed_documents([chunk.index_text for chunk in batch]),
            )
            if progress:
                progress(min(offset + len(batch), len(chunks)), len(chunks))

    def add_document(self, document_id: str, chunks: list[Chunk], progress=None) -> None:
        """Indexation incrementale : seuls les fragments de ce document sont vectorises."""
        try:
            self.delete_document(document_id, bump=False)
            self._upsert(chunks, progress)
        except StoreUnavailable:
            raise
        except Exception as error:  # pragma: no cover - Chroma / model boundary
            raise StoreUnavailable(f"Echec de l'indexation Chroma : {error}") from error
        self.version += 1

    def delete_document(self, document_id: str, bump: bool = True) -> None:
        try:
            self.collection.delete(where={"document_id": {"$eq": document_id}})
        except Exception as error:  # pragma: no cover - Chroma boundary
            raise StoreUnavailable(f"Suppression Chroma impossible : {error}") from error
        if bump:
            self.version += 1

    def delete_orphans(self, known_ids: set[str]) -> int:
        """Supprime les fragments sans document_id (ancienne ingestion globale) ou d'un document inconnu.

        Un filtre ``where document_id == ""`` ne trouve pas les fragments dont la cle est
        absente : on supprime donc par identifiant.
        """
        data = self.collection.get(include=["metadatas"])
        orphans = [
            item_id for item_id, metadata in zip(data.get("ids") or [], data.get("metadatas") or [])
            if str((metadata or {}).get("document_id") or "") not in known_ids
        ]
        for offset in range(0, len(orphans), 500):
            self.collection.delete(ids=orphans[offset : offset + 500])
        if orphans:
            self.version += 1
        return len(orphans)

    def document_chunk_counts(self) -> dict[str, int]:
        data = self.collection.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for metadata in data.get("metadatas") or []:
            key = str((metadata or {}).get("document_id") or "")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def document_chunks(self, document_id: str) -> list[RetrievedChunk]:
        data = self.collection.get(where={"document_id": {"$eq": document_id}}, include=["documents", "metadatas"])
        chunks = [self._to_chunk(i, t, m, 0.0) for i, t, m in zip(data.get("ids") or [], data.get("documents") or [], data.get("metadatas") or [])]
        return sorted(chunks, key=lambda chunk: chunk.id)

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
            document_id=str(metadata.get("document_id") or "") or None,
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


def write_manifest(path: Path, documents: list[dict[str, Any]], strategy: dict[str, Any]) -> None:
    """Ecrit le catalogue des documents de maniere atomique."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"documents": documents, "strategy": strategy}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("documents", [])
    except (OSError, json.JSONDecodeError) as error:
        raise StoreUnavailable(f"Manifeste d'index illisible : {error}") from error
