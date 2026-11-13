"""Extraction de PDF avec pages, metadonnees et tableaux contextualises."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from .models import DocumentMetadata, ExtractedPage


METADATA_LABELS = {
    "organisme emetteur": "issuer",
    "type de document": "document_type",
    "reference": "reference",
    "date de publication": "published_date",
    "version": "version",
    "statut": "status",
    "public vise": "audience",
}

FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}


_CID_PATTERN = re.compile(r"\(cid:(\d+)\)")


def _replace_cid(match: re.Match[str]) -> str:
    # pdfplumber rend les puces non mappees sous la forme "(cid:127)".
    return "•" if match.group(1) == "127" else ""


def normalize(value: str | None) -> str:
    """Compacte les espaces tout en preservant les caracteres francais."""
    value = _CID_PATTERN.sub(_replace_cid, value or "")
    return re.sub(r"\s+", " ", value).strip()


def normalized_key(value: str) -> str:
    """Normalise une cle de metadonnees pour une comparaison tolerante aux accents."""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return normalize(ascii_value).lower()


def parse_french_date(value: str | None) -> str | None:
    """Convertit une date francaise en ISO, sinon retourne ``None``."""
    if not value:
        return None
    simplified = normalized_key(value).replace("1er", "1")
    match = re.search(r"\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b", simplified)
    if not match or match.group(2) not in FRENCH_MONTHS:
        return None
    try:
        return date(int(match.group(3)), FRENCH_MONTHS[match.group(2)], int(match.group(1))).isoformat()
    except ValueError:
        return None


def _table_to_rows(table: list[list[str | None]], table_number: int) -> list[str]:
    """Transforme les lignes de tableau en texte avec le nom de chaque colonne."""
    normalized_rows = [
        [normalize(cell) for cell in row]
        for row in table
        if row and any(normalize(cell) for cell in row)
    ]
    if len(normalized_rows) < 2:
        return []

    headers = normalized_rows[0]
    rendered_rows: list[str] = []
    for row_number, row in enumerate(normalized_rows[1:], start=1):
        pairs = []
        for column, value in enumerate(row):
            if not value:
                continue
            header = headers[column] if column < len(headers) and headers[column] else f"Colonne {column + 1}"
            pairs.append(f"{header} : {value}")
        if pairs:
            rendered_rows.append(f"Tableau {table_number}, ligne {row_number} - " + " ; ".join(pairs))
    return rendered_rows


def _is_metadata_table(table: list[list[str | None]]) -> bool:
    labels = {normalized_key(normalize(row[0])) for row in table if row and row[0]}
    return len(labels & set(METADATA_LABELS)) >= 3


def _metadata_from_tables(tables: list[list[list[str | None]]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for table in tables:
        for row in table:
            if len(row) < 2 or not row[0]:
                continue
            field = METADATA_LABELS.get(normalized_key(normalize(row[0])))
            value = normalize(" ".join(cell or "" for cell in row[1:]))
            if field and value:
                values[field] = value
    return values


def _margin_signature(line: str) -> str:
    """Uniformise les numeros variables d'un en-tete/pied de page."""
    return re.sub(r"\bpage\s+\d+\b", "page #", normalized_key(line))


def _candidate_margin_lines(lines: list[str], margin_size: int = 3) -> set[str]:
    """Identifie les lignes repetees dans les marges hautes et basses des pages."""
    candidates: list[str] = []
    for page_lines in lines:
        compact = [normalize(line) for line in page_lines if normalize(line)]
        candidates.extend(_margin_signature(line) for line in compact[:margin_size])
        candidates.extend(_margin_signature(line) for line in compact[-margin_size:])
    counts = Counter(candidates)
    return {line for line, occurrences in counts.items() if occurrences >= 2 and len(line) >= 3}


def _remove_repeated_margins(lines: list[str], repeated_lines: set[str]) -> str:
    return "\n".join(
        normalized
        for line in lines
        if (normalized := normalize(line)) and _margin_signature(normalized) not in repeated_lines
    )


def _extract_page_text_with_tables(page: pdfplumber.page.Page, tables: list[object]) -> tuple[str, list[str]]:
    """Recompose une page en inserant chaque tableau a son emplacement logique.

    Extraire tous les tableaux a la fin de la page ferait rattacher, par exemple,
    le tableau du semestre impair au titre du semestre suivant. Cette fonction
    conserve donc l'ordre vertical du PDF : texte avant le tableau, lignes
    contextualisees du tableau, puis texte qui le suit.
    """
    if not tables:
        return page.extract_text() or "", []

    parts: list[str] = []
    all_rows: list[str] = []
    cursor = 0.0
    data_table_number = 0
    for table in sorted(tables, key=lambda item: item.bbox[1]):
        _, top, _, bottom = table.bbox
        if top > cursor:
            above = page.crop((0, cursor, page.width, top)).extract_text() or ""
            if above.strip():
                parts.append(above.strip())
        extracted_table = table.extract()
        if not _is_metadata_table(extracted_table):
            data_table_number += 1
            rows = _table_to_rows(extracted_table, data_table_number)
            parts.extend(rows)
            all_rows.extend(rows)
        cursor = max(cursor, bottom)

    if cursor < page.height:
        below = page.crop((0, cursor, page.width, page.height)).extract_text() or ""
        if below.strip():
            parts.append(below.strip())
    return "\n".join(parts), all_rows


def _title_from_page(text: str) -> str | None:
    lines = [normalize(line) for line in text.splitlines() if normalize(line)]
    ignored_prefixes = ("ecole d'ingenieurs helianthe", "organisme emetteur", "type de document")
    for line in lines:
        if not normalized_key(line).startswith(ignored_prefixes):
            return line
    return None


def extract_pdf(pdf_path: Path) -> tuple[DocumentMetadata, list[ExtractedPage]]:
    """Extrait un PDF sans modifier sa source.

    Les en-tetes et pieds de page ne sont supprimes que lorsqu'ils se repetent sur
    au moins deux pages. Les tableaux sont ajoutes sous forme de lignes ou chaque
    valeur conserve son en-tete de colonne.
    """
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        tables_by_page = [page.find_tables() for page in pdf.pages]
        extracted_pages = [_extract_page_text_with_tables(page, tables_by_page[index]) for index, page in enumerate(pdf.pages)]
        raw_page_lines = [text.splitlines() for text, _ in extracted_pages]
        first_page_tables = [table.extract() for table in tables_by_page[0]] if pdf.pages else []
        metadata_values = _metadata_from_tables(first_page_tables)
        repeated_margins = _candidate_margin_lines(raw_page_lines)

        pages: list[ExtractedPage] = []
        for page_number, page in enumerate(pdf.pages, start=1):
            text = _remove_repeated_margins(raw_page_lines[page_number - 1], repeated_margins)
            table_rows = extracted_pages[page_number - 1][1]
            pages.append(ExtractedPage(page=page_number, text=text, table_rows=tuple(table_rows)))

    reader = PdfReader(pdf_path)
    pdf_title = reader.metadata.title if reader.metadata else None
    metadata = DocumentMetadata(
        file=pdf_path.name,
        reference=metadata_values.get("reference"),
        document_type=metadata_values.get("document_type"),
        published_date=metadata_values.get("published_date"),
        published_at=parse_french_date(metadata_values.get("published_date")),
        version=metadata_values.get("version"),
        status=metadata_values.get("status"),
        issuer=metadata_values.get("issuer"),
        audience=metadata_values.get("audience"),
        title=normalize(pdf_title) or _title_from_page(pages[0].text if pages else ""),
        page_count=len(pages),
    )
    return metadata, pages
