"""Backend isole pour le test de bout en bout (Playwright).

- Donnees dans un dossier temporaire : l'index reel (data/chroma), la base SQLite et
  les documents d'origine ne sont jamais touches.
- Embedder deterministe (HashingEmbedder) et LLM scripte : le test ne depend ni du
  reseau ni d'une cle API, et ses reponses sont reproductibles.
- Le LLM factice cite toujours le premier extrait fourni ([1]) en recopiant sa
  premiere phrase, ce qui suffit a verifier televersement -> question -> citation.

Lancement : python frontend/e2e/server.py  (port 8001)
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from eih_rag.config import Settings  # noqa: E402
from eih_rag.main import create_app  # noqa: E402
from eih_rag.rag.embeddings import HashingEmbedder  # noqa: E402
from eih_rag.rag.service import RagService  # noqa: E402
from eih_rag.rag.store import ChromaStore  # noqa: E402

ADMIN_PASSWORD = "e2e-admin"


class ScriptedGenerator:
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if "questions de suivi" in system_prompt:
            return '["Quels sont les horaires ?", "Comment renouveler un emprunt ?", "Que se passe-t-il en cas de retard ?"]'
        if "question autonome" in system_prompt:
            return user_prompt.rsplit("\n", 1)[-1]
        return "".join(self.stream(system_prompt, user_prompt))

    def stream(self, system_prompt: str, user_prompt: str):
        match = re.search(r"\[1\][^\n]*\n(.+?)(?:\n\n|\n\[2\]|$)", user_prompt, flags=re.DOTALL)
        sentence = (match.group(1) if match else "").strip().split(". ")[0][:200]
        answer = f"D'après le règlement : {sentence} [1]."
        for word in answer.split(" "):
            yield word + " "


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="eih-e2e-"))
    settings = Settings(
        chroma_dir=work / "chroma", manifest_path=work / "manifest.json", db_path=work / "app.db",
        uploads_dir=work / "uploads", corpus_dir=work / "corpus", admin_password=ADMIN_PASSWORD, auth_secret="e2e",
        llm_provider="ollama", embedding_backend="hashing", reranker_enabled=False, score_threshold=0.05,
        chunk_size=400, chunk_overlap=50, default_top_k=3, cors_origins="http://localhost:5174",
    )
    store = ChromaStore(settings.chroma_dir, "e2e_chunks", HashingEmbedder(dimension=256))
    service = RagService(settings, store=store, generator=ScriptedGenerator())
    app = create_app(settings=settings, service=service, background=True, sync_corpus=False)
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")


if __name__ == "__main__":
    main()
