"""Tests des routes v2 : authentification, cycle de vie des documents, chat en flux, retours."""

import json

import pytest
from fastapi.testclient import TestClient

from eih_rag.config import Settings
from eih_rag.main import create_app
from eih_rag.rag.embeddings import HashingEmbedder
from eih_rag.rag.prompting import NO_ANSWER
from eih_rag.rag.service import RagService
from eih_rag.rag.store import ChromaStore

ADMIN_PASSWORD = "secret-de-test"


class FakeGenerator:
    """LLM factice : reponses deterministes selon le prompt systeme."""

    def __init__(self) -> None:
        self.answer = "Le parking est réservé aux vélos [1]."
        self.calls: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append(user_prompt)
        if "question autonome" in system_prompt:
            return "Quelles sont les règles du parking pour les vélos ?"
        if "questions de suivi" in system_prompt:
            return '["Où se trouve le parking ?", "Quels horaires ?", "Faut-il un badge ?"]'
        return self.answer

    def stream(self, system_prompt: str, user_prompt: str):
        self.calls.append(user_prompt)
        for word in self.answer.split(" "):
            yield word + " "


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        chroma_dir=tmp_path / "chroma", manifest_path=tmp_path / "manifest.json", db_path=tmp_path / "app.db",
        uploads_dir=tmp_path / "uploads", corpus_dir=tmp_path / "corpus", admin_password=ADMIN_PASSWORD,
        auth_secret="s", llm_provider="ollama", embedding_backend="hashing", reranker_enabled=False,
        score_threshold=0.05, max_upload_mb=1, chunk_size=400, chunk_overlap=50, default_top_k=3,
    )
    generator = FakeGenerator()
    store = ChromaStore(settings.chroma_dir, "test_chunks", HashingEmbedder(dimension=256))
    service = RagService(settings, store=store, generator=generator)
    client = TestClient(create_app(settings=settings, service=service, background=False, sync_corpus=False))
    token = client.post("/api/auth/login", json={"password": ADMIN_PASSWORD}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}, generator


def upload(client, headers, name, text, **form):
    data = {"title": form.pop("title", name), "doc_type": "Procédure", **form}
    return client.post("/api/documents", headers=headers, data=data, files={"file": (name, text.encode(), "text/plain")})


def events(response) -> list[tuple[str, dict]]:
    parsed = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


PARKING = "# Règlement du parking\n## Article 1 — Vélos\nLe parking à vélos est situé derrière le bâtiment B et ouvert de 7h à 22h."


def test_admin_routes_require_login(env):
    client, headers, _ = env
    assert client.post("/api/auth/login", json={"password": "faux"}).status_code == 401
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "admin"
    assert client.get("/api/auth/me").json()["role"] == "student"
    assert upload(client, {}, "a.txt", "texte").status_code == 401
    assert client.get("/api/admin/feedback").status_code == 401


def test_upload_is_validated(env):
    client, headers, _ = env
    rejected = client.post("/api/documents", headers=headers, data={"title": "x"}, files={"file": ("virus.exe", b"MZ...", "application/octet-stream")})
    assert rejected.status_code == 422
    fake_pdf = client.post("/api/documents", headers=headers, data={"title": "x"}, files={"file": ("doc.pdf", b"not a pdf", "application/pdf")})
    assert fake_pdf.status_code == 422
    too_big = upload(client, headers, "big.txt", "a" * (1024 * 1024 + 10))
    assert too_big.status_code == 422


def test_upload_index_search_version_and_delete(env):
    client, headers, _ = env
    created = upload(client, headers, "../../parking.txt", PARKING, title="Règlement du parking")
    assert created.status_code == 202
    document = created.json()["document"]
    assert document["file_name"] == "parking.txt"  # chemin neutralise
    job = client.get(f"/api/ingestion/{created.json()['job_id']}").json()
    assert job["stage"] == "indexed" and job["progress"] == 1.0
    listed = client.get("/api/documents").json()
    assert listed[0]["status"] == "indexed" and listed[0]["chunk_count"] >= 1
    assert client.get("/api/stats").json()["indexed_documents"] == 1

    hits = client.post("/api/search", json={"question": "parking vélos bâtiment B", "top_k": 3}).json()["fragments"]
    assert "bâtiment B" in hits[0]["excerpt"]
    assert client.get(f"/api/documents/{document['id']}/file").content == PARKING.encode()

    # Doublon exact et titre deja utilise
    assert upload(client, headers, "copie.txt", PARKING).json()["detail"]["code"] == "duplicate"
    same_title = upload(client, headers, "autre.txt", "Autre contenu", title="Règlement du parking")
    assert same_title.status_code == 409 and same_title.json()["detail"]["code"] == "title_exists"

    # Nouvelle version : l'ancienne sort de la recherche mais reste dans l'historique
    new_version = upload(client, headers, "parking-v2.txt", PARKING.replace("bâtiment B", "bâtiment C"), title="Règlement du parking", replace_id=document["id"])
    assert new_version.status_code == 202
    statuses = {d["id"]: d["status"] for d in client.get("/api/documents?history=true").json()}
    assert statuses[document["id"]] == "superseded"
    texts = [f["excerpt"] for f in client.post("/api/search", json={"question": "parking vélos bâtiment", "top_k": 5}).json()["fragments"]]
    assert any("bâtiment C" in t for t in texts) and not any("bâtiment B" in t for t in texts)

    # Suppression : plus aucun fragment
    new_id = new_version.json()["document"]["id"]
    assert client.delete(f"/api/documents/{new_id}", headers=headers).status_code == 204
    texts = [f["excerpt"] for f in client.post("/api/search", json={"question": "parking vélos bâtiment", "top_k": 5}).json()["fragments"]]
    assert not any("bâtiment C" in t for t in texts)


def test_upload_then_chat_cites_the_new_document(env):
    """Bout en bout cote API : televersement -> question -> reponse citant ce document."""
    client, headers, generator = env
    upload(client, headers, "parking.txt", PARKING, title="Règlement du parking")
    response = client.post("/api/chat", json={"message": "Où se trouve le parking à vélos ?"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    stream = events(response)
    names = [name for name, _ in stream]
    assert names[0] == "conversation" and "meta" in names and names.count("token") >= 2 and names[-1] == "done"
    done = stream[-1][1]
    assert done["found"] is True
    assert done["citations"][0]["title"] == "Règlement du parking" and done["citations"][0]["cited"] is True
    assert done["citations"][0]["document_id"] and "bâtiment B" in done["citations"][0]["passage"]
    assert len(done["followups"]) == 3

    # Relance : la question est reformulee avec l'historique avant la recherche
    conversation_id = done["conversation_id"]
    follow = events(client.post("/api/chat", json={"conversation_id": conversation_id, "message": "et le soir ?"}))
    meta = next(data for name, data in follow if name == "meta")
    assert meta["rewritten_query"] == "Quelles sont les règles du parking pour les vélos ?"
    conversation = client.get(f"/api/conversations/{conversation_id}").json()
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant", "user", "assistant"]


def test_not_found_and_feedback_reach_admin(env):
    client, headers, generator = env
    upload(client, headers, "parking.txt", PARKING, title="Règlement du parking")
    generator.answer = NO_ANSWER
    done = events(client.post("/api/chat", json={"message": "Quel est le prix du parking ?"}))[-1][1]
    assert done["found"] is False and done["citations"] == [] and done["answer"] == NO_ANSWER
    assert client.get("/api/admin/unanswered", headers=headers).json()[0]["question"] == "Quel est le prix du parking ?"

    assert client.post("/api/feedback", json={"message_id": done["message_id"], "rating": -1, "comment": "Info manquante"}).status_code == 201
    summary = client.get("/api/admin/feedback", headers=headers).json()
    assert summary["down"] == 1 and summary["negative"][0]["comment"] == "Info manquante"


def test_conversation_crud_and_attachment(env):
    client, headers, _ = env
    conversation = client.post("/api/conversations", json={}).json()
    assert client.patch(f"/api/conversations/{conversation['id']}", json={"title": "Mon stage"}).json()["title"] == "Mon stage"
    attached = client.post(f"/api/conversations/{conversation['id']}/attachments", files={"file": ("notes.md", "# Notes\nMon stage commence le 3 mars.".encode(), "text/markdown")})
    assert attached.status_code == 201 and attached.json()["chunks"] == 1
    done = events(client.post("/api/chat", json={"conversation_id": conversation["id"], "message": "Quand commence mon stage ?"}))[-1][1]
    attachment = next(c for c in done["citations"] if c["attachment"])
    assert attachment["official"] is False and attachment["doc_type"] == "Fichier joint"
    assert client.get("/api/conversations", params={"q": "Mon stage"}).json()[0]["id"] == conversation["id"]
    assert client.delete(f"/api/conversations/{conversation['id']}").status_code == 204
    assert client.get(f"/api/conversations/{conversation['id']}").status_code == 404


def test_chat_reports_llm_quota_clearly(env):
    from eih_rag.rag.llm import LLMQuotaExceeded

    client, headers, generator = env
    upload(client, headers, "parking.txt", PARKING, title="Règlement du parking")

    def exhausted(system_prompt, user_prompt):
        raise LLMQuotaExceeded(retry_after=417)
        yield  # pragma: no cover

    generator.stream = exhausted
    stream = events(client.post("/api/chat", json={"message": "Où se trouve le parking à vélos ?"}))
    error = next(data for name, data in stream if name == "error")
    assert error["code"] == "quota" and error["retry_after_min"] == 7
