"""Regression tests for the backend/frontend repository layout."""

from eih_rag.config import PROJECT_ROOT, Settings


def test_repository_layout():
    assert (PROJECT_ROOT / "backend" / "src" / "eih_rag" / "main.py").is_file()
    assert (PROJECT_ROOT / "frontend" / "package.json").is_file()
    assert (PROJECT_ROOT / "corpus").is_dir()
    assert (PROJECT_ROOT / "eval" / "testset.jsonl").is_file()


def test_default_storage_paths():
    settings = Settings(_env_file=None)
    assert settings.corpus_dir == PROJECT_ROOT / "corpus"
    assert settings.chroma_dir == PROJECT_ROOT / "data" / "chroma"
    assert settings.manifest_path == PROJECT_ROOT / "data" / "index_manifest.json"
