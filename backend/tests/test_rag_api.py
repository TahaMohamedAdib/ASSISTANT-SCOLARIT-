from fastapi.testclient import TestClient

from eih_rag.config import Settings
from eih_rag.main import create_app
from eih_rag.rag.service import RagService
from eih_rag.rag.store import RetrievedChunk
from eih_rag.schemas import AskRequest, IngestRequest, SearchRequest


class FakeStore:
    def __init__(self, hits: list[RetrievedChunk] | None = None) -> None:
        self.hits = hits or []

    def count(self) -> int:
        return 7

    def search(self, question: str, top_k: int, document_type: str | None = None) -> list[RetrievedChunk]:
        return self.hits[:top_k]


class FakeGenerator:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.answer


def hit(score: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        id="EIH-1:structural:0001",
        chunk_id="abc",
        text="Le repas coute 25 dirhams.",
        file="guide.pdf",
        reference="EIH-GUIDE",
        date="1er septembre 2026",
        page=2,
        section="2.3 Restauration",
        score=score,
    )


def make_service(tmp_path, hits, answer, threshold=0.28):
    settings = Settings(chroma_dir=tmp_path / "chroma", manifest_path=tmp_path / "manifest.json", score_threshold=threshold)
    return RagService(settings, store=FakeStore(hits), generator=FakeGenerator(answer))


def test_refusal_threshold_does_not_call_llm(tmp_path):
    service = make_service(tmp_path, [hit(score=0.1)], "Cette reponse ne doit jamais etre utilisee.", threshold=0.5)
    result = service.ask(AskRequest(question="Question hors corpus", top_k=5))
    assert result.found is False
    assert result.sources == []
    assert service.generator.calls == 0


def test_invalid_citations_are_reported(tmp_path):
    service = make_service(tmp_path, [hit()], "Le repas coute 25 dirhams. [2]")
    result = service.ask(AskRequest(question="Quel est le prix du repas ?", top_k=5))
    assert result.found is True
    assert result.invalid_citations == [2]


def test_api_exposes_docs_and_rejects_blank_search_question(tmp_path):
    service = make_service(tmp_path, [hit()], "Le repas coute 25 dirhams. [1]")
    app = create_app(service=service)
    client = TestClient(app)

    assert client.get("/docs").status_code == 200
    assert client.get("/api/health").json()["indexed_fragments"] == 7
    assert client.post("/api/search", json={"question": "   "}).status_code == 422


def test_api_ask_returns_sources_and_latency(tmp_path):
    service = make_service(tmp_path, [hit()], "Le repas coute 25 dirhams. [1]")
    client = TestClient(create_app(service=service))
    response = client.post("/api/ask", json={"question": "Quel est le prix du repas ?", "top_k": 1, "filters": {"type": None}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["sources"][0]["page"] == 2
    assert payload["invalid_citations"] == []
    assert payload["latency_ms"] >= 0
