"""Modeles de donnees serialisables pour la premiere seance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentMetadata:
    """Metadonnees utiles a la recherche et a la gestion de versions."""

    file: str
    reference: str | None
    document_type: str | None
    published_date: str | None
    published_at: str | None
    version: str | None
    status: str | None
    issuer: str | None
    audience: str | None
    title: str | None
    page_count: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Alias explicites demandes dans l'enonce ; les noms longs restent
        # disponibles pour rendre le schema auto-documente.
        payload["type"] = self.document_type
        payload["date"] = self.published_date
        return payload


@dataclass(frozen=True)
class ExtractedPage:
    """Texte nettoye et lignes de tableaux d'une page de PDF."""

    page: int
    text: str
    table_rows: tuple[str, ...]

    @property
    def searchable_text(self) -> str:
        # ``text`` contient deja les lignes de tableaux a leur position dans
        # la page. ``table_rows`` est conserve pour inspection et tests.
        return self.text.strip()


@dataclass(frozen=True)
class Chunk:
    """Un fragment pret a etre indexe lors de la seance suivante."""

    id: str
    chunk_id: str
    text: str
    strategy: str
    chunk_size: int
    overlap: int
    file: str
    reference: str | None
    document_type: str | None
    published_date: str | None
    published_at: str | None
    version: str | None
    status: str | None
    page: int
    section: str | None
    # Titre du document et chemin complet des titres (ex. "Titre IV > Article 9 > 9.2").
    title: str | None = None
    section_path: str | None = None

    @property
    def index_text(self) -> str:
        """Texte indexe (dense + BM25) : en-tete contextuel + contenu.

        L'en-tete rattache un fragment isole (ligne de tableau, sous-article)
        a son document et a sa hierarchie de titres, ce qui ameliore le rappel.
        """
        header = " > ".join(part for part in (self.title, self.section_path) if part)
        return f"{header}\n{self.text}" if header else self.text

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["type"] = self.document_type
        payload["date"] = self.published_date
        return payload
