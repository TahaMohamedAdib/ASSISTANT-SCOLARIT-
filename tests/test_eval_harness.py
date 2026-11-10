import json
from pathlib import Path
from types import SimpleNamespace

from eih_rag.rag.llm import _duration
from eih_rag.rag.prompting import NO_ANSWER, PROMPTS, is_refusal


def test_groq_reset_header_is_parsed():
    assert float(_duration("45.885s")) == 45.885
    assert float(_duration("1m26.4s")) == 86.4
    assert float(_duration("585ms")) == 0.585
    assert _duration("") is None


def test_refusal_detection_tolerates_quotes():
    assert is_refusal(NO_ANSWER)
    assert is_refusal(f"« {NO_ANSWER} »")
    assert not is_refusal("Le stage dure 8 semaines [1].")
    assert NO_ANSWER in PROMPTS["v1"] and NO_ANSWER in PROMPTS["v2"]


def test_evidence_metrics_accept_alternative_wordings():
    from eval.experiments import evidence_metrics

    hits = [SimpleNamespace(text="Inscription avant le 12 février 2027."), SimpleNamespace(text="Note plafonnée à 12/20.")]
    metrics = evidence_metrics(hits, [["Vendredi 12 février 2027", "12 février 2027"], "plafonnée à 12/20"])
    assert metrics == {"recall": 1.0, "full_recall": 1.0, "rr": 1.0}
    assert evidence_metrics(hits, ["absent du texte"])["full_recall"] == 0.0


def test_extended_testset_covers_all_question_types():
    rows = [json.loads(line) for line in Path("eval/testset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = {row["category"] for row in rows}
    assert len(rows) >= 50
    assert categories == {"factual", "numeric_table", "yes_no", "multi_part", "multi_doc", "version", "summary", "vague", "out_of_corpus"}
    assert all(row["evidence"] for row in rows if row["expected_found"])
    assert all(not row["evidence"] for row in rows if not row["expected_found"])
