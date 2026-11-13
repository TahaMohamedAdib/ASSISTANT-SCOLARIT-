"""Strategies de decoupage fixe et structurel, sans framework RAG."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .extraction import normalize
from .models import Chunk, DocumentMetadata, ExtractedPage


_TITRE = re.compile(r"^Titre\s+(?:[IVXLCDM]+|\d+)\s*[-–—].+", re.IGNORECASE)
_ARTICLE = re.compile(r"^Article\s+\d+\s*[-–—].+", re.IGNORECASE)
_FAQ = re.compile(r"^Q\d+\.\s+.+", re.IGNORECASE)
# "1. Presentation" ou "5.2 Choix du sujet" ; le point final est facultatif apres un sous-numero.
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")


def _numbered_heading_level(line: str) -> int | None:
    """Niveau d'un titre numerote, ou None pour un element de liste numerotee.

    Les listes ("1. avoir acquis les 180 credits ;") partagent la syntaxe des
    titres ; un titre est court, commence par une majuscule et ne se termine
    pas par une ponctuation de phrase.
    """
    match = _NUMBERED.match(line)
    if not match:
        return None
    number, label = match.groups()
    if "." not in number and not re.match(r"^\d+\.\s", line):
        return None
    if not label[:1].isupper() or label.rstrip()[-1:] in ".;,:" or len(label.split()) > 10:
        return None
    return 2 + number.count(".")


def heading_level(line: str) -> int | None:
    """1 = Titre, 2 = Article / section / question FAQ, 3+ = sous-section."""
    line = line.strip()
    if _TITRE.match(line):
        return 1
    if _ARTICLE.match(line) or _FAQ.match(line):
        return 2
    return _numbered_heading_level(line)


def validate_chunk_parameters(chunk_size: int, overlap: int) -> None:
    if chunk_size < 50:
        raise ValueError("La taille de fragment doit etre d'au moins 50 caracteres.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("Le chevauchement doit etre positif ou nul et inferieur a la taille.")


def is_heading(line: str) -> bool:
    return heading_level(line) is not None


def _cut_at_boundary(text: str, start: int, desired_end: int) -> int:
    """Evite si possible de couper au milieu d'un mot ou d'une phrase."""
    if desired_end >= len(text):
        return len(text)
    lower_bound = start + max(1, (desired_end - start) * 3 // 5)
    candidates = [text.rfind("\n", lower_bound, desired_end), text.rfind(". ", lower_bound, desired_end), text.rfind(" ", lower_bound, desired_end)]
    boundary = max(candidates)
    if boundary <= start:
        return desired_end
    return boundary + (1 if text[boundary] == "\n" else 0)


def split_fixed_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Decoupe un texte par taille, avec chevauchement configurable."""
    validate_chunk_parameters(chunk_size, overlap)
    text = text.strip()
    if not text:
        return []

    parts: list[str] = []
    start = 0
    while start < len(text):
        end = _cut_at_boundary(text, start, min(start + chunk_size, len(text)))
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        # Le chevauchement est calcule en caracteres, mais le debut d'un
        # fragment doit rester au debut d'un mot pour ne pas produire
        # d'extraits tels que "tudiants".
        if next_start < len(text) and not text[next_start].isspace() and not text[next_start - 1].isspace():
            previous_separator = max(text.rfind(" ", start, next_start), text.rfind("\n", start, next_start))
            if previous_separator >= start:
                next_start = previous_separator + 1
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        start = next_start
    return parts


def _make_chunk(
    *,
    text: str,
    strategy: str,
    chunk_size: int,
    overlap: int,
    metadata: DocumentMetadata,
    page: int,
    section: str | None,
    index: int,
    section_path: str | None = None,
) -> Chunk:
    text = text.strip()
    digest_source = "|".join([metadata.file, strategy, str(page), section or "", text])
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
    return Chunk(
        id=f"{metadata.reference or metadata.file}:{strategy}:{index:04d}",
        chunk_id=digest,
        text=text,
        strategy=strategy,
        chunk_size=chunk_size,
        overlap=overlap,
        file=metadata.file,
        reference=metadata.reference,
        document_type=metadata.document_type,
        published_date=metadata.published_date,
        published_at=metadata.published_at,
        version=metadata.version,
        status=metadata.status,
        page=page,
        section=section,
        title=metadata.title,
        section_path=section_path or section,
    )


def fixed_chunks(
    pages: Iterable[ExtractedPage], metadata: DocumentMetadata, chunk_size: int, overlap: int
) -> list[Chunk]:
    """Decoupe chaque page a taille fixe afin de garder un numero de page exact."""
    chunks: list[Chunk] = []
    for page in pages:
        for text in split_fixed_text(page.searchable_text, chunk_size, overlap):
            chunks.append(
                _make_chunk(
                    text=text,
                    strategy="fixed",
                    chunk_size=chunk_size,
                    overlap=overlap,
                    metadata=metadata,
                    page=page.page,
                    section=None,
                    index=len(chunks) + 1,
                )
            )
    return chunks


def _structural_units(pages: Iterable[ExtractedPage]) -> list[tuple[int, str | None, str | None, str]]:
    """Regroupe les lignes d'un meme article, titre ou couple Q/R.

    Retourne des tuples ``(page, section, section_path, texte)``. La pile de
    titres est conservee d'une page a l'autre : la suite d'un article sur la
    page suivante garde son titre. Un titre immediatement suivi d'un autre
    titre (ex. "Titre II" puis "Article 3") ne produit pas de fragment vide ;
    il reste visible dans ``section_path``.
    """
    units: list[tuple[int, str | None, str | None, str]] = []
    stack: dict[int, str] = {}
    buffer: list[str] = []
    has_body = False

    def current() -> tuple[str | None, str | None]:
        if not stack:
            return None, None
        levels = sorted(stack)
        return stack[levels[-1]], " > ".join(stack[level] for level in levels)

    def flush(page_number: int) -> None:
        nonlocal buffer, has_body
        if buffer and has_body:
            section, path = current()
            units.append((page_number, section, path, "\n".join(buffer)))
        buffer, has_body = [], False

    for page in pages:
        for raw_line in page.searchable_text.splitlines():
            line = normalize(raw_line)
            if not line:
                continue
            level = heading_level(line)
            if level is None:
                buffer.append(line)
                has_body = True
                continue
            flush(page.page)
            for deeper in [existing for existing in stack if existing >= level]:
                del stack[deeper]
            stack[level] = line
            buffer = [line]
        flush(page.page)
    return units


def structural_chunks(
    pages: Iterable[ExtractedPage], metadata: DocumentMetadata, chunk_size: int, overlap: int
) -> list[Chunk]:
    """Decoupe en suivant les titres, articles et questions de FAQ.

    Une unite longue est ensuite sous-decoupee pour respecter la taille maximale.
    ``section`` est le titre le plus specifique, ``section_path`` la hierarchie
    complete ; les numeros de page restent exacts.
    """
    validate_chunk_parameters(chunk_size, overlap)
    chunks: list[Chunk] = []
    for page_number, section, section_path, unit in _structural_units(pages):
        for text in split_fixed_text(unit, chunk_size, overlap):
            chunks.append(
                _make_chunk(
                    text=text,
                    strategy="structural",
                    chunk_size=chunk_size,
                    overlap=overlap,
                    metadata=metadata,
                    page=page_number,
                    section=section,
                    section_path=section_path,
                    index=len(chunks) + 1,
                )
            )
    return chunks


def create_chunks(
    pages: Iterable[ExtractedPage],
    metadata: DocumentMetadata,
    strategy: str,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[Chunk]:
    """Point d'entree unique pour choisir une strategie de decoupage."""
    if strategy == "fixed":
        return fixed_chunks(pages, metadata, chunk_size, overlap)
    if strategy == "structural":
        return structural_chunks(pages, metadata, chunk_size, overlap)
    raise ValueError("Strategie inconnue : choisissez 'fixed' ou 'structural'.")
