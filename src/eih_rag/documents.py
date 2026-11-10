"""Registre des documents et ingestion incrementale en tache de fond.

Cycle de vie d'un document :
    televerse -> (en attente de validation) -> analyse -> decoupage -> vectorisation -> indexe
                                                                          \\-> echec (+ raison)
Les 7 PDF de ``corpus/`` forment le corpus de base : ils sont enregistres au
demarrage, lus mais jamais modifies ni supprimes du disque. Les fichiers
televerses sont stockes dans ``data/uploads/<id>/`` (hors du frontend servi).

Indexation incrementale : ajouter, remplacer ou supprimer un document ne
touche que ses propres fragments dans Chroma ; le reste du corpus n'est jamais
re-vectorise.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from .chunking import create_chunks
from .config import Settings
from .db import Database, new_id, now
from .loaders import load_document, safe_filename, validate_upload
from .models import DocumentMetadata
from .rag.store import ChromaStore

DOC_TYPES = ("Règlement", "Calendrier", "Procédure", "Convention de stage", "Guide PFE", "FAQ", "Note de service", "Guide", "Autre")
STAGES = ("uploaded", "parsing", "chunking", "embedding", "indexed")


class DocumentConflict(Exception):
    def __init__(self, code: str, message: str, document_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.document_id = document_id


class DocumentService:
    def __init__(self, settings: Settings, db: Database, store: ChromaStore, background: bool = True) -> None:
        self.settings = settings
        self.db = db
        self.store = store
        self.background = background
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingestion")
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ base corpus
    def sync_base_corpus(self) -> list[str]:
        """Enregistre les PDF de corpus/ et (re)indexe ce qui manque dans Chroma.

        Retourne les identifiants des taches lancees. Idempotent : un
        redemarrage n'indexe rien si Chroma est deja a jour.
        """
        jobs: list[str] = []
        known = {row["sha256"]: row for row in self.db.all("SELECT * FROM documents WHERE is_base = 1")}
        for pdf in sorted(Path(self.settings.corpus_dir).glob("*.pdf")):
            content = pdf.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            if sha in known:
                continue
            metadata, _ = load_document(pdf, ".pdf")
            document_id = new_id()
            self.db.insert("documents", {
                "id": document_id, "title": metadata.title or pdf.stem, "doc_type": metadata.document_type,
                "department": None, "effective_date": metadata.published_at, "version": metadata.version,
                "official": 1, "reference": metadata.reference, "file_name": pdf.name, "stored_path": str(pdf),
                "sha256": sha, "size": len(content), "extension": ".pdf", "status": "uploaded", "is_base": 1,
                "uploaded_by": "corpus initial", "uploaded_at": now(),
            })
        # Fragments herites de l'ancienne ingestion globale (sans document_id) ou orphelins : supprimes.
        active = {row["id"] for row in self.db.all("SELECT id FROM documents WHERE status NOT IN ('superseded', 'removed')")}
        if self.store.count():
            self.store.delete_orphans(active)
        counts = self.store.document_chunk_counts() if self.store.count() else {}
        for row in self.db.all("SELECT * FROM documents WHERE status IN ('uploaded', 'processing', 'indexed')"):
            if row["status"] != "indexed" or counts.get(row["id"], 0) == 0:
                jobs.append(self.enqueue(row["id"]))
        return jobs

    # ------------------------------------------------------------------ upload
    def upload(
        self,
        file_name: str,
        content: bytes,
        metadata: dict[str, Any],
        uploaded_by: str = "admin",
        replace_id: str | None = None,
        allow_same_title: bool = False,
    ) -> dict[str, Any]:
        extension = validate_upload(file_name, content, self.settings.max_upload_mb * 1024 * 1024)
        sha = hashlib.sha256(content).hexdigest()
        duplicate = self.db.one("SELECT * FROM documents WHERE sha256 = ? AND status != 'superseded'", (sha,))
        if duplicate:
            raise DocumentConflict("duplicate", f"Ce fichier est déjà présent (« {duplicate['title']} »).", duplicate["id"])
        title = (metadata.get("title") or Path(file_name).stem).strip()[:200]
        if replace_id:
            previous = self.db.document(replace_id)
            if not previous or previous["status"] == "superseded":
                raise DocumentConflict("not_found", "Le document à remplacer n'existe pas.", replace_id)
        elif not allow_same_title:
            same = self.db.one(
                "SELECT * FROM documents WHERE lower(title) = lower(?) AND status NOT IN ('superseded', 'removed')", (title,)
            )
            if same:
                raise DocumentConflict("title_exists", f"Un document intitulé « {same['title']} » existe déjà.", same["id"])

        document_id = new_id()
        folder = Path(self.settings.uploads_dir) / document_id
        folder.mkdir(parents=True, exist_ok=True)
        stored = folder / safe_filename(file_name)
        stored.write_bytes(content)
        self.db.insert("documents", {
            "id": document_id, "title": title, "doc_type": metadata.get("doc_type") or "Autre",
            "department": metadata.get("department") or None, "effective_date": metadata.get("effective_date") or None,
            "version": metadata.get("version") or None, "official": 1 if metadata.get("official", True) else 0,
            "reference": metadata.get("reference") or None, "file_name": safe_filename(file_name), "stored_path": str(stored),
            "sha256": sha, "size": len(content), "extension": extension,
            "status": "pending_review" if self.settings.require_review else "uploaded", "is_base": 0,
            "uploaded_by": uploaded_by, "uploaded_at": now(), "replaces_id": replace_id,
        })
        job_id = None if self.settings.require_review else self.enqueue(document_id)
        return {"document": self.public(self.db.document(document_id)), "job_id": job_id}

    def approve(self, document_id: str) -> str:
        document = self._require(document_id)
        if document["status"] != "pending_review":
            raise DocumentConflict("invalid_state", "Ce document n'est pas en attente de validation.", document_id)
        return self.enqueue(document_id)

    # ------------------------------------------------------------------ jobs
    def enqueue(self, document_id: str) -> str:
        job_id = new_id()
        stamp = now()
        self.db.insert("jobs", {"id": job_id, "document_id": document_id, "stage": "uploaded", "progress": 0.0, "created_at": stamp, "updated_at": stamp})
        self.db.update("documents", document_id, {"status": "processing", "error": None})
        if self.background:
            self._executor.submit(self._ingest, job_id, document_id)
        else:
            self._ingest(job_id, document_id)
        return job_id

    def _stage(self, job_id: str, stage: str, progress: float, error: str | None = None) -> None:
        self.db.update("jobs", job_id, {"stage": stage, "progress": round(progress, 3), "error": error, "updated_at": now()})

    def _ingest(self, job_id: str, document_id: str) -> None:
        with self._lock:  # une ingestion a la fois : Chroma et le modele d'embedding sont partages
            document = self.db.document(document_id)
            try:
                self._stage(job_id, "parsing", 0.1)
                detected, pages = load_document(Path(document["stored_path"]), document["extension"])
                if not any(page.text.strip() for page in pages):
                    raise ValueError("Aucun texte exploitable n'a été trouvé (document scanné ou vide ?).")
                metadata = DocumentMetadata(
                    file=document["file_name"],
                    reference=document["reference"] or (detected.reference if detected else None),
                    document_type=document["doc_type"] or (detected.document_type if detected else None),
                    published_date=document["effective_date"] or (detected.published_date if detected else None),
                    published_at=document["effective_date"] or (detected.published_at if detected else None),
                    version=document["version"] or (detected.version if detected else None),
                    status=None, issuer=None, audience=None,
                    title=document["title"], page_count=len(pages),
                )
                self._stage(job_id, "chunking", 0.3)
                chunks = create_chunks(pages, metadata, "structural", self.settings.chunk_size, self.settings.chunk_overlap)
                chunks = [replace(chunk, id=f"{document_id}:{index:04d}", document_id=document_id) for index, chunk in enumerate(chunks, start=1)]
                if not chunks:
                    raise ValueError("Le découpage n'a produit aucun fragment.")
                self._stage(job_id, "embedding", 0.4)
                self.store.add_document(
                    document_id, chunks, progress=lambda done, total: self._stage(job_id, "embedding", 0.4 + 0.55 * done / total)
                )
                stamp = now()
                self.db.update("documents", document_id, {
                    "status": "indexed", "chunk_count": len(chunks), "page_count": len(pages), "indexed_at": stamp, "error": None,
                })
                if document["replaces_id"]:  # nouvelle version : l'ancienne sort de l'index actif mais reste dans l'historique
                    self.store.delete_document(document["replaces_id"])
                    self.db.update("documents", document["replaces_id"], {"status": "superseded"})
                self._stage(job_id, "indexed", 1.0)
            except Exception as error:  # l'echec est visible dans l'UI avec sa raison
                message = str(error) or error.__class__.__name__
                self.db.update("documents", document_id, {"status": "failed", "error": message[:500]})
                self._stage(job_id, "failed", 1.0, message[:500])

    def job(self, job_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def latest_job(self, document_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM jobs WHERE document_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (document_id,))

    def wait(self) -> None:
        """Attend la fin des taches en cours (tests, scripts)."""
        self._executor.submit(lambda: None).result()

    # ------------------------------------------------------------------ maintenance
    def reindex(self, document_id: str) -> str:
        document = self._require(document_id)
        if document["status"] == "superseded":
            raise DocumentConflict("invalid_state", "Une ancienne version ne peut pas être réindexée.", document_id)
        return self.enqueue(document_id)

    def reindex_all(self) -> list[str]:
        rows = self.db.all("SELECT id FROM documents WHERE status NOT IN ('superseded', 'pending_review')")
        return [self.enqueue(row["id"]) for row in rows]

    def delete(self, document_id: str) -> None:
        """Retire le document de la recherche. Les PDF du corpus initial restent sur le disque."""
        document = self._require(document_id)
        self.store.delete_document(document_id)
        if document["is_base"]:
            self.db.update("documents", document_id, {"status": "removed", "chunk_count": 0})
            return
        self.db.execute("DELETE FROM jobs WHERE document_id = ?", (document_id,))
        self.db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        folder = Path(self.settings.uploads_dir) / document_id
        if folder.is_dir() and folder.resolve().is_relative_to(Path(self.settings.uploads_dir).resolve()):
            shutil.rmtree(folder)

    def file_path(self, document_id: str) -> Path:
        return Path(self._require(document_id)["stored_path"])

    def _require(self, document_id: str) -> dict[str, Any]:
        document = self.db.document(document_id)
        if not document:
            raise DocumentConflict("not_found", "Document introuvable.", document_id)
        return document

    # ------------------------------------------------------------------ lecture
    def list(self, include_history: bool = False) -> list[dict[str, Any]]:
        return [self.public(row) for row in self.db.documents(include_history)]

    def stats(self) -> dict[str, Any]:
        row = self.db.one("SELECT COUNT(*) AS n, MAX(indexed_at) AS last FROM documents WHERE status = 'indexed'")
        pending = self.db.one("SELECT COUNT(*) AS n FROM documents WHERE status IN ('uploaded', 'processing')")
        return {"indexed_documents": row["n"], "last_updated": row["last"], "processing": pending["n"], "chunks": self.store.count()}

    def public(self, row: dict[str, Any]) -> dict[str, Any]:
        job = self.latest_job(row["id"])
        return {
            "id": row["id"], "title": row["title"], "doc_type": row["doc_type"], "department": row["department"],
            "effective_date": row["effective_date"], "version": row["version"], "official": bool(row["official"]),
            "reference": row["reference"], "file_name": row["file_name"], "size": row["size"], "extension": row["extension"],
            "status": row["status"], "is_base": bool(row["is_base"]), "page_count": row["page_count"],
            "chunk_count": row["chunk_count"], "uploaded_by": row["uploaded_by"], "uploaded_at": row["uploaded_at"],
            "indexed_at": row["indexed_at"], "replaces_id": row["replaces_id"], "error": row["error"],
            "job": job and {"id": job["id"], "stage": job["stage"], "progress": job["progress"], "error": job["error"]},
            # Alias de compatibilite avec l'ancienne route /api/documents
            "file": row["file_name"], "type": row["doc_type"], "date": row["effective_date"],
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["DOC_TYPES", "STAGES", "DocumentConflict", "DocumentService", "Future"]
