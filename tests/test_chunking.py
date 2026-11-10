from pathlib import Path

import pytest

from eih_rag.chunking import create_chunks, is_heading, split_fixed_text, validate_chunk_parameters
from eih_rag.extraction import _table_to_rows, parse_french_date
from eih_rag.models import DocumentMetadata, ExtractedPage


METADATA = DocumentMetadata(
    file="guide.pdf",
    reference="EIH-TEST-2026",
    document_type="Guide",
    published_date="5 octobre 2026",
    published_at="2026-10-05",
    version="1.0",
    status="En vigueur",
    issuer="EIH",
    audience="Etudiants",
    title="Guide de test",
    page_count=1,
)


def test_fixed_split_keeps_configured_overlap():
    text = "mot " * 80
    chunks = split_fixed_text(text, chunk_size=100, overlap=20)
    assert len(chunks) >= 2
    assert chunks[0][-15:] in chunks[1]


def test_fixed_split_never_starts_in_the_middle_of_a_word():
    chunks = split_fixed_text("premier " + ("extraordinaire " * 20), chunk_size=100, overlap=17)
    assert all(chunk.split(maxsplit=1)[0] in {"premier", "extraordinaire"} for chunk in chunks)


def test_structural_strategy_keeps_article_as_section():
    page = ExtractedPage(
        page=1,
        text="Titre I - Regles\nArticle 1 - Objet\nUne premiere regle.\nArticle 2 - Suite\nUne seconde regle.",
        table_rows=(),
    )
    chunks = create_chunks([page], METADATA, "structural", chunk_size=100, overlap=10)
    # "Titre I" n'a pas de contenu propre : il ne produit pas de fragment vide
    # mais reste visible dans la hierarchie de chaque article.
    assert [chunk.section for chunk in chunks] == ["Article 1 - Objet", "Article 2 - Suite"]
    assert [chunk.section_path for chunk in chunks] == ["Titre I - Regles > Article 1 - Objet", "Titre I - Regles > Article 2 - Suite"]
    assert "Une seconde regle" in chunks[-1].text
    assert chunks[0].index_text.startswith("Guide de test > Titre I - Regles > Article 1 - Objet\n")


def test_structural_section_carries_over_page_break():
    pages = [
        ExtractedPage(page=1, text="Article 9 - Absences\nDebut de l'article.\n3. Semestres pairs", table_rows=()),
        ExtractedPage(page=2, text="Tableau 1, ligne 1 - Date : 8 fevrier", table_rows=()),
    ]
    chunks = create_chunks(pages, METADATA, "structural", chunk_size=200, overlap=10)
    assert chunks[-1].page == 2
    assert chunks[-1].section == "3. Semestres pairs"


def test_numbered_list_items_are_not_headings():
    assert is_heading("2. Formes de mobilité proposées")
    assert is_heading("9.2 Absence justifiée")
    assert not is_heading("1. être inscrit en 2A au moment de la candidature ;")
    assert not is_heading("1. Prendre rendez-vous avec le référent accessibilité du BVE.")
    assert not is_heading("2. Déposer la demande accompagnée d'un certificat médical récent avant le 30 octobre, ou")


def test_cid_bullets_are_cleaned():
    from eih_rag.extraction import normalize

    assert normalize("(cid:127) IGL — Informatique") == "• IGL — Informatique"


def test_table_rows_keep_headers():
    rows = _table_to_rows([["Date", "Evenement"], ["12 fevrier 2027", "Rattrapage"]], table_number=1)
    assert rows == ["Tableau 1, ligne 1 - Date : 12 fevrier 2027 ; Evenement : Rattrapage"]


def test_page_searchable_text_does_not_duplicate_table_rows():
    page = ExtractedPage(page=1, text="Introduction\nTableau 1, ligne 1 - Date : 12", table_rows=("Tableau 1, ligne 1 - Date : 12",))
    assert page.searchable_text.count("Tableau 1") == 1


def test_serialized_chunk_exposes_required_short_metadata_keys():
    page = ExtractedPage(page=1, text="Article 1 - Objet\nTexte.", table_rows=())
    payload = create_chunks([page], METADATA, "fixed", chunk_size=50, overlap=0)[0].to_dict()
    assert payload["type"] == "Guide"
    assert payload["date"] == "5 octobre 2026"


def test_french_date_is_normalized_to_iso():
    assert parse_french_date("1er septembre 2026") == "2026-09-01"


@pytest.mark.parametrize("chunk_size,overlap", [(49, 0), (100, -1), (100, 100)])
def test_invalid_chunk_parameters_are_rejected(chunk_size, overlap):
    with pytest.raises(ValueError):
        validate_chunk_parameters(chunk_size, overlap)


def test_corpus_contains_exactly_seven_pdfs():
    corpus = Path(__file__).resolve().parents[1] / "corpus"
    assert len(list(corpus.glob("*.pdf"))) == 7
