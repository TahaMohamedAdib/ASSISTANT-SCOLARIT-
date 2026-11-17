import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from eih_rag.config import PROJECT_ROOT, Settings
from eih_rag.main import create_app
from eih_rag.rag import service as service_module
from eih_rag.rag.service import RagService
from eih_rag.rag.store import StoreUnavailable


OFFICIAL = "01_Reglement_des_etudes_2026-2027.pdf"


def pdf_bytes(text: str | None = "Un certificat particulier est disponible.") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    if text is not None:
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }),
            }),
        })
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 10 200 Td ({text}) Tj ET".encode("ascii"))
        page.replace_contents(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def api(tmp_path):
    settings = Settings(
        corpus_dir=tmp_path / "corpus",
        uploads_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        manifest_path=tmp_path / "state" / "manifest.json",
        embedding_backend="hashing",
        max_upload_bytes=128 * 1024,
    )
    settings.corpus_dir.mkdir()
    shutil.copyfile(PROJECT_ROOT / "corpus" / OFFICIAL, settings.corpus_dir / OFFICIAL)
    service = RagService(settings)
    with TestClient(create_app(service=service)) as client:
        yield client, service


def upload(client, name, content=None):
    return client.post("/api/documents/upload", files={
        "file": (name, pdf_bytes() if content is None else content, "application/pdf"),
    })


def test_upload_list_reingest_and_delete(api):
    client, service = api
    # A single official file exercises the removal of the fixed corpus size.
    response = client.post("/api/ingest", json={"strategy": "fixed", "chunk_size": 500, "overlap": 50})
    assert response.status_code == 200
    assert response.json()["documents_indexed"] == 1

    filename = "Rentrée (2027).PDF"
    response = upload(client, filename)
    assert response.status_code == 201, response.text
    assert response.json()["origin"] == "upload"
    assert response.json()["chunk_count"] == 1
    assert (service.settings.uploads_dir / filename).is_file()
    assert {doc["file"]: doc["origin"] for doc in client.get("/api/documents").json()} == {
        OFFICIAL: "official", filename: "upload",
    }
    manifest = json.loads(service.settings.manifest_path.read_text(encoding="utf-8"))
    assert manifest["strategy"] == {"strategy": "fixed", "chunk_size": 500, "overlap": 50}
    hits = service.search_hits("certificat particulier", 10, None)
    assert any(hit.file == filename and hit.origin == "upload" for hit in hits)

    assert client.post("/api/ingest").json()["documents_indexed"] == 2
    assert RagService(service.settings).documents()[-1].file == filename

    response = client.delete(f"/api/documents/{quote(filename)}")
    assert response.status_code == 204
    assert response.content == b""
    assert not (service.settings.uploads_dir / filename).exists()
    assert [doc["file"] for doc in client.get("/api/documents").json()] == [OFFICIAL]
    assert all(hit.file != filename for hit in service.search_hits("certificat particulier", 10, None))


@pytest.mark.parametrize(("filename", "content", "expected"), [
    ("guide.docx", b"not a PDF", 415),
    ("guide.pdf", b"not a PDF", 415),
    ("guide.pdf", b"%PDF-1.7\ninvalid", 415),
    ("guide.pdf", pdf_bytes(None), 415),
    ("guide.pdf", b"%PDF-" + b"x" * (128 * 1024), 413),
    ("../guide.pdf", pdf_bytes(), 400),
    (r"..\guide.pdf", pdf_bytes(), 400),
    ("C:guide.pdf", pdf_bytes(), 400),
    ("CON.pdf", pdf_bytes(), 400),
])
def test_rejects_invalid_uploads(api, filename, content, expected):
    client, service = api
    response = upload(client, filename, content)
    assert response.status_code == expected, response.text
    assert client.get("/api/documents").json() == []
    assert not service.settings.manifest_path.exists()
    assert not list(service.settings.uploads_dir.glob("*.pdf"))


def test_conflicts_and_protected_deletion(api):
    client, service = api
    assert upload(client, "Guide.pdf").status_code == 201
    assert upload(client, "GUIDE.PDF", pdf_bytes("Autre texte.")).status_code == 409
    assert upload(client, OFFICIAL.upper()).status_code == 409
    original = service.settings.corpus_dir / OFFICIAL
    before = original.read_bytes()
    assert client.delete(f"/api/documents/{OFFICIAL}").status_code == 403
    assert original.read_bytes() == before
    assert client.delete("/api/documents/absent.pdf").status_code == 404
    assert client.delete("/api/documents/..%5Cguide.pdf").status_code == 400

def test_symlink_cannot_delete_official_pdf(api):
    client, service = api
    original = service.settings.corpus_dir / OFFICIAL
    before = original.read_bytes()
    service.settings.uploads_dir.mkdir()
    link = service.settings.uploads_dir / "lien.pdf"
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("Les liens symboliques ne sont pas disponibles dans cet environnement.")
    assert client.delete("/api/documents/lien.pdf").status_code == 404
    assert original.read_bytes() == before


def test_identical_references_keep_distinct_chunks(api):
    client, service = api
    content = (service.settings.corpus_dir / OFFICIAL).read_bytes()
    assert upload(client, "copie.pdf", content).status_code == 201
    chunks, _ = service.store.all_chunks()
    assert {chunk.file for chunk in chunks} == {OFFICIAL, "copie.pdf"}
    assert len(chunks) == sum(doc["chunk_count"] for doc in client.get("/api/documents").json())


@pytest.mark.parametrize("failure", ["embedding", "manifest"])
def test_failed_rebuild_keeps_existing_state(api, monkeypatch, failure):
    client, service = api
    assert upload(client, "present.pdf").status_code == 201
    manifest = service.settings.manifest_path.read_bytes()
    before = client.get("/api/documents").json()
    chunks_before = service.store.all_chunks()[0]

    def fail(*args, **kwargs):
        raise StoreUnavailable("Panne simulee.")

    if failure == "embedding":
        monkeypatch.setattr(service.store.embedder, "embed_documents", fail)
    else:
        monkeypatch.setattr(service_module, "write_manifest", fail)

    assert upload(client, "nouveau.pdf").status_code == 503
    assert client.delete("/api/documents/present.pdf").status_code == 503
    assert client.post("/api/ingest").status_code == 503
    assert service.settings.manifest_path.read_bytes() == manifest
    assert client.get("/api/documents").json() == before
    assert service.store.all_chunks()[0] == chunks_before
    assert sorted(path.name for path in service.settings.uploads_dir.iterdir()) == ["present.pdf"]


def test_concurrent_duplicate_uploads(api):
    client, _ = api
    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = list(executor.map(lambda _: upload(client, "guide.pdf").status_code, range(2)))
    assert sorted(codes) == [201, 409]
    assert sum(doc["file"] == "guide.pdf" for doc in client.get("/api/documents").json()) == 1


def test_existing_manifest_without_origin_remains_readable(api):
    client, service = api
    legacy = {"documents": [{"file": OFFICIAL, "page_count": 5, "chunk_count": 9}]}
    service.settings.manifest_path.parent.mkdir()
    service.settings.manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert client.get("/api/documents").json()[0]["origin"] == "official"


def test_large_streamed_request_is_rejected_before_ingestion(api):
    client, service = api
    boundary = "test-boundary"

    def body():
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="guide.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("ascii")
        for _ in range(8):
            yield b"x" * (32 * 1024)
        yield f"\r\n--{boundary}--\r\n".encode("ascii")

    response = client.post(
        "/api/documents/upload", content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413, response.text
    assert not service.settings.uploads_dir.exists()
