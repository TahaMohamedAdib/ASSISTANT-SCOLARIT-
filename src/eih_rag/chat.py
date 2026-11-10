"""Conversation multi-tours avec reponse en flux (Server-Sent Events).

Deroulement d'un tour :
    1. relance ("et pour le stage ?") -> reformulee en question autonome a l'aide de l'historique ;
    2. recherche hybride dans le corpus officiel (+ fichier joint eventuel) ;
    3. seuil de pertinence : en dessous, refus sans appel au LLM ;
    4. generation en flux, citations [n], detection du refus ;
    5. suggestions de questions de suivi, persistance, journal des questions sans reponse.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from time import perf_counter
from typing import Any

import numpy as np

from .chunking import create_chunks
from .config import Settings
from .db import Database, new_id, now
from .loaders import load_document, validate_upload
from .models import DocumentMetadata
from .rag.llm import OpenAICompatibleGenerator, strip_thinking
from .rag.prompting import NO_ANSWER, SYSTEM_PROMPT, build_user_prompt, is_refusal, mentions_not_found
from .rag.service import RagService
from .rag.store import RetrievedChunk

FOLLOWUP_REWRITE_PROMPT = """Tu reformules la DERNIERE question d'un etudiant en une question autonome, en francais,
comprehensible sans l'historique (remplace "et pour...", "ca", "il", etc. par les termes explicites).
Si elle est deja autonome, recopie-la telle quelle. Ne reponds pas a la question.
Reponds uniquement par la question reformulee, sur une ligne."""

SUGGESTIONS_PROMPT = """A partir de la question d'un etudiant et de la reponse obtenue (fondee sur les documents officiels
de son ecole), propose 3 questions de suivi courtes (moins de 12 mots), naturelles et differentes, auxquelles les memes
documents peuvent probablement repondre. Reponds uniquement par un tableau JSON de 3 chaines."""


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatService:
    def __init__(self, settings: Settings, db: Database, rag: RagService) -> None:
        self.settings = settings
        self.db = db
        self.rag = rag
        # Modele secondaire sur un quota distinct ; a defaut, le generateur principal.
        if settings.llm_provider == "openai_compatible" and settings.aux_model:
            self.aux = OpenAICompatibleGenerator(settings.openai_base_url, settings.aux_model, settings.openai_api_key)
        else:
            self.aux = rag.generator

    # ------------------------------------------------------------------ conversations
    def create_conversation(self, title: str = "Nouvelle conversation") -> dict[str, Any]:
        conversation_id = new_id()
        stamp = now()
        self.db.insert("conversations", {"id": conversation_id, "title": title[:120], "created_at": stamp, "updated_at": stamp})
        return self.db.conversation(conversation_id)

    def list_conversations(self, query: str = "") -> list[dict[str, Any]]:
        if query:
            like = f"%{query}%"
            return self.db.all(
                """SELECT DISTINCT c.* FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.title LIKE ? OR m.content LIKE ? ORDER BY c.updated_at DESC""",
                (like, like),
            )
        return self.db.all("SELECT * FROM conversations ORDER BY updated_at DESC")

    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        conversation = self.db.conversation(conversation_id)
        if not conversation:
            return None
        feedback = {row["message_id"]: row for row in self.db.all("SELECT * FROM feedback WHERE conversation_id = ?", (conversation_id,))}
        messages = self.db.messages(conversation_id)
        for message in messages:
            rating = feedback.get(message["id"])
            message["feedback"] = rating and {"rating": rating["rating"], "comment": rating["comment"]}
        attachments = self.db.all("SELECT id, file_name, created_at FROM attachments WHERE conversation_id = ?", (conversation_id,))
        return {**conversation, "messages": messages, "attachments": attachments}

    def rename(self, conversation_id: str, title: str) -> None:
        self.db.update("conversations", conversation_id, {"title": title.strip()[:120] or "Sans titre", "updated_at": now()})

    def delete(self, conversation_id: str) -> None:
        self.db.execute("DELETE FROM feedback WHERE conversation_id = ?", (conversation_id,))
        self.db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    # ------------------------------------------------------------------ pieces jointes (mode B)
    def attach(self, conversation_id: str, file_name: str, content: bytes) -> dict[str, Any]:
        """Fichier temporaire : vectorise pour cette conversation seulement, jamais ajoute au corpus."""
        extension = validate_upload(file_name, content, self.settings.max_upload_mb * 1024 * 1024)
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"attachment{extension}"
            path.write_bytes(content)
            _, pages = load_document(path, extension)
        metadata = DocumentMetadata(file=file_name, reference=None, document_type="attachment", published_date=None, published_at=None,
                                    version=None, status=None, issuer=None, audience=None, title=f"Fichier joint : {file_name}", page_count=len(pages))
        chunks = create_chunks(pages, metadata, "structural", self.settings.chunk_size, self.settings.chunk_overlap)
        if not chunks:
            raise ValueError("Aucun texte exploitable dans le fichier joint.")
        vectors = self.rag.store.embedder.embed_documents([chunk.index_text for chunk in chunks])
        payload = [{"text": chunk.text, "page": chunk.page, "section": chunk.section, "vector": vector} for chunk, vector in zip(chunks, vectors)]
        attachment_id = new_id()
        self.db.insert("attachments", {"id": attachment_id, "conversation_id": conversation_id, "file_name": file_name[:200],
                                       "chunks": json.dumps(payload), "created_at": now()})
        return {"id": attachment_id, "file_name": file_name, "chunks": len(chunks)}

    def _attachment_hits(self, conversation_id: str, query: str, limit: int = 3) -> list[RetrievedChunk]:
        rows = self.db.all("SELECT * FROM attachments WHERE conversation_id = ?", (conversation_id,))
        if not rows:
            return []
        query_vector = np.asarray(self.rag.store.embedder.embed_query(query), dtype=float)
        scored = []
        for row in rows:
            for index, chunk in enumerate(json.loads(row["chunks"])):
                score = float(np.asarray(chunk["vector"], dtype=float) @ query_vector)
                scored.append((score, row, index, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedChunk(
                id=f"attachment:{row['id']}:{index}", chunk_id=f"{row['id']}:{index}", text=chunk["text"], file=row["file_name"],
                reference=None, date=None, page=chunk["page"], section=chunk.get("section"), score=round(score, 4),
                title=f"Fichier joint : {row['file_name']}", document_type="attachment", relevance=round(score, 4),
                document_id=None, methods=("attachment",),
            )
            for score, row, index, chunk in scored[:limit]
        ]

    # ------------------------------------------------------------------ chat
    def _standalone_question(self, history: list[dict[str, Any]], message: str) -> str:
        turns = [m for m in history if m["role"] in ("user", "assistant")][-2 * self.settings.history_turns :]
        if not turns:
            return message
        transcript = "\n".join(f"{'Etudiant' if m['role'] == 'user' else 'Assistant'}: {m['content'][:600]}" for m in turns)
        try:
            rewritten = strip_thinking(self.aux.generate(FOLLOWUP_REWRITE_PROMPT, f"HISTORIQUE:\n{transcript}\n\nDERNIERE QUESTION:\n{message}"))
            rewritten = rewritten.strip().strip('"«» ').splitlines()[0].strip() if rewritten.strip() else ""
            return rewritten if 3 <= len(rewritten) <= 400 else message
        except Exception:
            return message

    def _followups(self, question: str, answer: str) -> list[str]:
        try:
            raw = strip_thinking(self.aux.generate(SUGGESTIONS_PROMPT, f"QUESTION:\n{question}\n\nREPONSE:\n{answer[:1500]}"))
            match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
            items = json.loads(match.group(0)) if match else []
            return [str(item).strip() for item in items if str(item).strip()][:3]
        except Exception:
            return []

    @staticmethod
    def citation(index: int, hit: RetrievedChunk, cited: bool = False) -> dict[str, Any]:
        attachment = hit.document_type == "attachment"
        return {
            "id": index, "chunk_id": hit.id, "document_id": hit.document_id, "title": hit.title or hit.file,
            "doc_type": "Fichier joint" if attachment else hit.document_type, "reference": hit.reference, "file": hit.file,
            "page": hit.page, "section": hit.section_path or hit.section, "passage": hit.text,
            "score": hit.relevance if hit.relevance is not None else hit.score, "methods": list(hit.methods),
            "official": not attachment, "attachment": attachment, "date": hit.date, "cited": cited,
        }

    def stream(
        self,
        conversation_id: str | None,
        message: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        regenerate: bool = False,
    ) -> Iterator[str]:
        started = perf_counter()
        timings: dict[str, int] = {}
        if not conversation_id or not self.db.conversation(conversation_id):
            conversation_id = self.create_conversation(message.strip()[:80] or "Nouvelle conversation")["id"]
        history = self.db.messages(conversation_id)
        if regenerate:
            # Regenerer : on retire la derniere reponse et on rejoue la derniere question.
            last_users = [m for m in history if m["role"] == "user"]
            if last_users:
                message = last_users[-1]["content"]
                self.db.execute("DELETE FROM messages WHERE conversation_id = ? AND role = 'assistant' AND created_at >= ?", (conversation_id, last_users[-1]["created_at"]))
                history = [m for m in history if m["created_at"] < last_users[-1]["created_at"]]
        else:
            if len(history) == 0:
                self.db.update("conversations", conversation_id, {"title": message.strip()[:80]})
            self.db.add_message(conversation_id, "user", message)
        yield sse("conversation", {"conversation_id": conversation_id})

        query = message
        if history:
            yield sse("status", {"stage": "rewriting"})
            step = perf_counter()
            query = self._standalone_question(history, message)
            timings["rewrite_ms"] = round((perf_counter() - step) * 1000)

        yield sse("status", {"stage": "searching"})
        step = perf_counter()
        top_k = top_k or self.settings.default_top_k
        hits = self.rag.search_hits(query, top_k, doc_type)
        hits = hits + self._attachment_hits(conversation_id, query)
        timings["retrieval_ms"] = round((perf_counter() - step) * 1000)
        best = max(((h.relevance if h.relevance is not None else h.score) for h in hits), default=None)
        citations = [self.citation(index, hit) for index, hit in enumerate(hits, start=1)]
        debug = {
            "original_query": message, "rewritten_query": query if query != message else None,
            "retrieval": [{"n": c["id"], "title": c["title"], "page": c["page"], "section": c["section"], "score": c["score"], "methods": c["methods"]} for c in citations],
            "best_score": best, "threshold": self.settings.score_threshold,
        }
        yield sse("meta", {"rewritten_query": debug["rewritten_query"], "citations": citations})

        answer = ""
        stopped = True
        try:
            if best is None or best < self.settings.score_threshold:
                answer = NO_ANSWER
                yield sse("token", {"text": answer})
            else:
                yield sse("status", {"stage": "generating"})
                step = perf_counter()
                for token in self.rag.generator.stream(SYSTEM_PROMPT, build_user_prompt(query, hits)):
                    answer += token
                    yield sse("token", {"text": token})
                timings["generation_ms"] = round((perf_counter() - step) * 1000)
            stopped = False
        except Exception as error:  # pragma: no cover - fournisseur LLM
            answer = answer or ""
            yield sse("error", {"code": "llm_unavailable", "message": "Le modèle de langage ne répond pas pour le moment."})
            stopped = False
            self._save_assistant(conversation_id, answer, citations, debug, timings, started, error=str(error))
            return
        finally:
            if stopped:  # flux interrompu par l'utilisateur (bouton Stop) : on garde la reponse partielle
                self._save_assistant(conversation_id, answer, citations, debug, timings, started, stopped=True)

        refused = is_refusal(answer)
        found = not refused
        partial = found and mentions_not_found(answer)
        cited_numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
        for citation in citations:
            citation["cited"] = citation["id"] in cited_numbers
        if refused or partial:
            self.db.insert("unanswered", {"id": new_id(), "question": query, "conversation_id": conversation_id, "created_at": now()})
        followups = self._followups(query, answer) if found else []
        timings["total_ms"] = round((perf_counter() - started) * 1000)
        message_id = self._save_assistant(
            conversation_id, NO_ANSWER if refused else answer, citations if found else [], debug, timings, started,
            found=found, partial=partial, followups=followups,
        )
        yield sse("done", {
            "message_id": message_id, "conversation_id": conversation_id, "found": found, "partial": partial,
            "answer": NO_ANSWER if refused else answer, "citations": citations if found else [], "followups": followups,
            "debug": {**debug, "timings": timings},
        })

    def _save_assistant(self, conversation_id, answer, citations, debug, timings, started, **extra) -> str:
        timings = {**timings, "total_ms": round((perf_counter() - started) * 1000)}
        payload = {"citations": citations, "debug": {**debug, "timings": timings}, **extra}
        payload.setdefault("found", bool(answer) and not is_refusal(answer))
        return self.db.add_message(conversation_id, "assistant", answer, payload)

    # ------------------------------------------------------------------ feedback
    def feedback(self, message_id: str, rating: int, comment: str | None) -> None:
        message = self.db.one("SELECT * FROM messages WHERE id = ? AND role = 'assistant'", (message_id,))
        if not message:
            raise KeyError(message_id)
        question = self.db.one(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND created_at <= ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (message["conversation_id"], message["created_at"]),
        )
        self.db.execute("DELETE FROM feedback WHERE message_id = ?", (message_id,))
        self.db.insert("feedback", {
            "id": new_id(), "message_id": message_id, "conversation_id": message["conversation_id"], "rating": 1 if rating > 0 else -1,
            "comment": (comment or "").strip()[:1000] or None, "question": question and question["content"], "answer": message["content"],
            "created_at": now(),
        })

    def feedback_summary(self) -> dict[str, Any]:
        counts = self.db.one("SELECT SUM(rating = 1) AS up, SUM(rating = -1) AS down FROM feedback") or {}
        worst = self.db.all("SELECT question, answer, comment, created_at FROM feedback WHERE rating = -1 ORDER BY created_at DESC LIMIT 50")
        return {"up": counts.get("up") or 0, "down": counts.get("down") or 0, "negative": worst}

    def unanswered(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT question, COUNT(*) AS count, MAX(created_at) AS last_asked FROM unanswered GROUP BY lower(question) ORDER BY count DESC, last_asked DESC LIMIT 200"
        )

    def citation_stats(self) -> list[dict[str, Any]]:
        """Documents les plus cites dans les reponses (page Sources)."""
        counts: dict[str, dict[str, Any]] = {}
        for row in self.db.all("SELECT payload FROM messages WHERE role = 'assistant'"):
            payload = json.loads(row["payload"] or "{}")
            for citation in payload.get("citations", []):
                if citation.get("cited") and citation.get("document_id"):
                    entry = counts.setdefault(citation["document_id"], {"document_id": citation["document_id"], "title": citation["title"], "count": 0})
                    entry["count"] += 1
        return sorted(counts.values(), key=lambda item: item["count"], reverse=True)
