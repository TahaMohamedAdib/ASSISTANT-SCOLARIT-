"""Configuration centralisee, chargee depuis les variables d'environnement."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parametres du backend. Aucune cle n'est ecrite dans le depot."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        populate_by_name=True,
        extra="ignore",
    )

    app_name: str = "Assistant Scolarite EIH"
    corpus_dir: Path = PROJECT_ROOT / "corpus"
    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    manifest_path: Path = PROJECT_ROOT / "data" / "index_manifest.json"
    collection_name: str = "eih_chunks"
    embedding_backend: str = "sentence_transformers"
    embedding_model: str = "intfloat/multilingual-e5-base"
    score_threshold: float = Field(default=0.28, ge=-1.0, le=1.0)
    default_top_k: int = Field(default=6, ge=1, le=20)
    # Decoupage par defaut (CLI) ; valeurs retenues apres les experiences (eval/RESULTS.md)
    chunk_size: int = Field(default=1200, ge=50, le=5000)
    chunk_overlap: int = Field(default=200, ge=0, le=2000)
    # Recherche hybride (voir rag/retrieval.py)
    retrieval_mode: str = "hybrid"  # dense | bm25 | hybrid
    hybrid_dense_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=100)
    reranker_enabled: bool = False  # mesure : n'ameliore pas le rappel ici, x10 plus lent
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_candidates: int = Field(default=20, ge=1, le=100)
    query_expansion: bool = False
    llm_provider: str = "ollama"
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias=AliasChoices("RAG_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"))
    ollama_model: str = Field(default="llama3.2", validation_alias=AliasChoices("RAG_OLLAMA_MODEL", "OLLAMA_MODEL"))
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias=AliasChoices("RAG_OPENAI_BASE_URL", "OPENAI_BASE_URL"))
    openai_model: str = Field(default="", validation_alias=AliasChoices("RAG_OPENAI_MODEL", "OPENAI_MODEL"))
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("RAG_OPENAI_API_KEY", "OPENAI_API_KEY"))
    cors_origins: str = "http://localhost:5173"

    # ---- Application v2 : base, televersements, administration, chat
    db_path: Path = PROJECT_ROOT / "data" / "app.db"
    # Hors de tout dossier servi publiquement ; les fichiers ne sont lus que via l'API.
    uploads_dir: Path = PROJECT_ROOT / "data" / "uploads"
    admin_password: str = Field(default="", validation_alias=AliasChoices("RAG_ADMIN_PASSWORD", "ADMIN_PASSWORD"))
    auth_secret: str = Field(default="", validation_alias=AliasChoices("RAG_AUTH_SECRET", "AUTH_SECRET"))
    max_upload_mb: int = Field(default=20, ge=1, le=200)
    # Si vrai, un document televerse reste "en attente de validation" jusqu'a approbation.
    require_review: bool = False
    contact_email: str = "scolarite@eih.ma"
    contact_phone: str = "+212 5 22 00 00 00"
    # Modele secondaire (quota distinct chez Groq) : reformulation des relances et suggestions.
    aux_model: str = "qwen/qwen3.8-27b"
    # Attente maximale (s) quand le quota du LLM est atteint, avant d'afficher une erreur a l'etudiant.
    llm_max_wait_s: float = Field(default=20.0, ge=0, le=600)
    history_turns: int = Field(default=3, ge=0, le=10)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
