from eih_rag.models import Chunk
from eih_rag.rag.embeddings import HashingEmbedder
from eih_rag.rag.store import ChromaStore


def make_chunk() -> Chunk:
    return Chunk(
        id="EIH-TEST:fixed:0001",
        chunk_id="chunk-test",
        text="Le restaurant sert le dejeuner aux etudiants.",
        strategy="fixed",
        chunk_size=500,
        overlap=100,
        file="guide.pdf",
        reference="EIH-TEST",
        document_type="Guide pratique",
        published_date="1er septembre 2026",
        published_at="2026-09-01",
        version="1.0",
        status="En vigueur",
        page=1,
        section="Restauration",
    )


def test_chroma_rebuild_is_persistent_and_idempotent(tmp_path):
    store = ChromaStore(tmp_path / "chroma", "test_chunks", HashingEmbedder(dimension=32))
    chunk = make_chunk()
    store.rebuild([chunk])
    assert store.count() == 1
    store.rebuild([chunk])
    assert store.count() == 1
    result = store.search("restaurant etudiant", top_k=1, document_type="Guide pratique")
    assert result[0].id == chunk.id


def test_orphan_chunks_without_document_id_are_removed(tmp_path):
    from dataclasses import replace

    store = ChromaStore(tmp_path / "chroma", "test_chunks", HashingEmbedder(dimension=32))
    legacy = make_chunk()  # ancienne ingestion : pas de document_id
    store.rebuild([legacy])
    store.add_document("doc1", [replace(legacy, id="doc1:0001", document_id="doc1")])
    assert store.count() == 2
    assert store.delete_orphans({"doc1"}) == 1
    assert [hit.id for hit in store.search("restaurant", top_k=5)] == ["doc1:0001"]
