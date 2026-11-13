from eih_rag.models import Chunk
from eih_rag.rag.embeddings import HashingEmbedder
from eih_rag.rag.retrieval import HybridRetriever, LLMQueryRewriter, RetrievalConfig, tokenize
from eih_rag.rag.store import ChromaStore


def chunk(index: int, text: str, section: str) -> Chunk:
    return Chunk(
        id=f"DOC:structural:{index:04d}",
        chunk_id=f"c{index}",
        text=text,
        strategy="structural",
        chunk_size=500,
        overlap=100,
        file="doc.pdf",
        reference="DOC",
        document_type="Guide",
        published_date=None,
        published_at=None,
        version=None,
        status=None,
        page=1,
        section=section,
        title="Guide de test",
        section_path=section,
    )


CHUNKS = [
    chunk(1, "La bibliotheque est ouverte de 8h30 a 20h00.", "2.1 Bibliotheque"),
    chunk(2, "La convention de stage est deposee 15 jours avant le debut.", "2.2 Convention de stage"),
    chunk(3, "Le restaurant sert le dejeuner de 11h45 a 14h00.", "2.3 Restauration"),
]


class FakeReranker:
    def score(self, query, passages):
        return [0.9 if "Restauration" in passage else 0.1 for passage in passages]


class FakeGenerator:
    def __init__(self, answer):
        self.answer = answer

    def generate(self, system_prompt, user_prompt):
        return self.answer


def make_store(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "test_chunks", HashingEmbedder(dimension=64))
    store.rebuild(CHUNKS)
    return store


def test_tokenize_strips_accents_stopwords_and_plurals():
    assert tokenize("Les conventions de stage déposées") == ["convention", "stage", "deposee"]
    assert "12/20" in tokenize("moyenne de 12/20")


def test_bm25_finds_exact_terms(tmp_path):
    retriever = HybridRetriever(make_store(tmp_path), RetrievalConfig(mode="bm25", rerank=False))
    assert retriever.search("convention de stage", top_k=1)[0].id == "DOC:structural:0002"


def test_hybrid_returns_relevance_and_reranker_reorders(tmp_path):
    store = make_store(tmp_path)
    plain = HybridRetriever(store, RetrievalConfig(mode="hybrid", rerank=False)).search("bibliotheque horaires", top_k=3)
    assert plain[0].id == "DOC:structural:0001"
    assert all(hit.relevance is not None for hit in plain)

    reranked = HybridRetriever(store, RetrievalConfig(mode="hybrid", rerank=True), reranker=FakeReranker()).search("bibliotheque horaires", top_k=3)
    assert reranked[0].section == "2.3 Restauration"
    assert reranked[0].relevance == 0.9


def test_bm25_cache_is_rebuilt_after_reingestion(tmp_path):
    store = make_store(tmp_path)
    retriever = HybridRetriever(store, RetrievalConfig(mode="bm25", rerank=False))
    retriever.search("bibliotheque", top_k=1)
    store.rebuild(CHUNKS[:1])
    assert len(retriever.search("restaurant dejeuner bibliotheque", top_k=5)) == 1


def test_query_rewriter_parses_json_and_survives_garbage():
    assert LLMQueryRewriter(FakeGenerator('Voici: ["duree PFE", "depot rapport PFE"]')).rewrite("PFE ?") == ["duree PFE", "depot rapport PFE"]
    assert LLMQueryRewriter(FakeGenerator("pas du json")).rewrite("PFE ?") == []
