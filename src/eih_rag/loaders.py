"""Chargement multi-formats et validation des fichiers televerses.

Chaque format est converti en ``ExtractedPage`` (texte + lignes de tableaux
contextualisees), puis decoupe par la meme strategie structurelle que les PDF.
Le contenu d'un fichier est toujours traite comme une DONNEE : il n'est jamais
execute ni interprete comme une instruction.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

from .extraction import _table_to_rows, extract_pdf, normalize
from .models import DocumentMetadata, ExtractedPage

ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".html", ".htm")
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK"}


class UploadRejected(ValueError):
    """Fichier refuse : type non autorise, trop volumineux, vide ou illisible."""


def safe_filename(name: str) -> str:
    """Nom de fichier sur : sans chemin, sans caracteres speciaux, longueur bornee."""
    name = Path(name.replace("\\", "/")).name
    stem, extension = Path(name).stem, Path(name).suffix.lower()
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("._-")[:80] or "document"
    return f"{ascii_stem}{extension}"


def validate_upload(file_name: str, content: bytes, max_bytes: int) -> str:
    """Verifie extension, taille et signature ; retourne l'extension normalisee."""
    extension = Path(file_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"Type de fichier non autorisé ({extension or 'sans extension'}). Formats acceptés : {', '.join(ALLOWED_EXTENSIONS)}.")
    if not content:
        raise UploadRejected("Le fichier est vide.")
    if len(content) > max_bytes:
        raise UploadRejected(f"Fichier trop volumineux ({len(content) / 1e6:.1f} Mo, maximum {max_bytes / 1e6:.0f} Mo).")
    magic = MAGIC.get(extension)
    if magic and not content.startswith(magic):
        raise UploadRejected("Le contenu du fichier ne correspond pas à son extension.")
    if extension not in MAGIC:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content.decode("cp1252")
            except UnicodeDecodeError as error:
                raise UploadRejected("Le fichier texte n'est pas lisible (encodage inconnu).") from error
    return extension


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _markdown_page(text: str) -> list[ExtractedPage]:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return [ExtractedPage(page=1, text="\n".join(line for line in lines if line.strip()), table_rows=())]


def _docx_pages(content: bytes) -> list[ExtractedPage]:
    from docx import Document

    document = Document(io.BytesIO(content))
    lines: list[str] = []
    rows: list[str] = []
    body = document.element.body
    table_number = 0
    paragraphs = {id(p._p): p for p in document.paragraphs}
    tables = {id(t._tbl): t for t in document.tables}
    for element in body.iterchildren():
        if id(element) in paragraphs:
            paragraph = paragraphs[id(element)]
            text = normalize(paragraph.text)
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
            match = re.search(r"(heading|titre)\s*(\d)", style)
            lines.append(f"{'#' * int(match.group(2))} {text}" if match else text)
        elif id(element) in tables:
            table_number += 1
            table = [[cell.text for cell in row.cells] for row in tables[id(element)].rows]
            table_rows = _table_to_rows(table, table_number)
            rows.extend(table_rows)
            lines.extend(table_rows)
    return [ExtractedPage(page=1, text="\n".join(lines), table_rows=tuple(rows))]


def _csv_pages(content: bytes) -> list[ExtractedPage]:
    text = _decode(content)
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
    table = [row for row in csv.reader(io.StringIO(text), dialect)]
    rows = _table_to_rows(table, 1)
    return [ExtractedPage(page=1, text="\n".join(rows), table_rows=tuple(rows))]


def _xlsx_pages(content: bytes) -> list[ExtractedPage]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    pages = []
    for number, sheet in enumerate(workbook.worksheets, start=1):
        table = [["" if value is None else str(value) for value in row] for row in sheet.iter_rows(values_only=True)]
        rows = _table_to_rows(table, 1)
        if rows:
            pages.append(ExtractedPage(page=number, text=f"# Feuille {sheet.title}\n" + "\n".join(rows), table_rows=tuple(rows)))
    return pages


def _html_pages(content: bytes) -> list[ExtractedPage]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_decode(content), "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "form"]):
        tag.decompose()
    lines: list[str] = []
    rows: list[str] = []
    table_number = 0
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        if element.name == "table":
            table_number += 1
            table = [[cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])] for tr in element.find_all("tr")]
            table_rows = _table_to_rows(table, table_number)
            rows.extend(table_rows)
            lines.extend(table_rows)
        elif element.find_parent("table") is None:
            text = normalize(element.get_text(" ", strip=True))
            if text:
                lines.append(f"{'#' * int(element.name[1])} {text}" if element.name.startswith("h") else text)
    return [ExtractedPage(page=1, text="\n".join(lines), table_rows=tuple(rows))]


def load_document(path: Path, extension: str) -> tuple[DocumentMetadata | None, list[ExtractedPage]]:
    """Retourne (metadonnees detectees ou None, pages). Seuls les PDF officiels EIH ont un cartouche."""
    if extension == ".pdf":
        metadata, pages = extract_pdf(path)
        return metadata, pages
    content = path.read_bytes()
    if extension == ".docx":
        pages = _docx_pages(content)
    elif extension == ".xlsx":
        pages = _xlsx_pages(content)
    elif extension == ".csv":
        pages = _csv_pages(content)
    elif extension in (".html", ".htm"):
        pages = _html_pages(content)
    else:  # .txt, .md
        pages = _markdown_page(_decode(content))
    return None, pages
