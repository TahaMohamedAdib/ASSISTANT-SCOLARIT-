import json
from pathlib import Path
from types import SimpleNamespace

from eih_rag.rag.llm import _duration
from eih_rag.rag.prompting import NO_ANSWER, PROMPTS, invalid_citations, is_refusal, normalize_citations


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


def test_fullwidth_citations_are_normalized():
    answer = normalize_citations("Durée de 18 semaines 【1】 【3】, voir aussi 【2†source】 et [4].")
    assert answer == "Durée de 18 semaines [1] [3], voir aussi [2] et [4]."
    assert invalid_citations(answer, 3) == [4]


def test_attachments_get_their_own_section_and_plain_prompts_are_unchanged():
    from eih_rag.rag.prompting import ATTACHMENT_HEADER, build_user_prompt
    from eih_rag.rag.store import RetrievedChunk

    def hit(text, kind):
        return RetrievedChunk(id=text, chunk_id=text, text=text, file="f.md", reference=None, date=None, page=1, section=None, score=0.9, document_type=kind)

    plain = build_user_prompt("Q ?", [hit("officiel", "Règlement")])
    assert plain == "EXTRAITS OFFICIELS:\n[1] Document: non renseignee | Reference: non renseignee | Date: non renseignee | Page: 1\nofficiel\n\nQUESTION ETUDIANTE:\nQ ?\n\nREPONSE:"
    mixed = build_user_prompt("Q ?", [hit("officiel", "Règlement"), hit("mes notes", "attachment")])
    official_part, attached_part = mixed.split(ATTACHMENT_HEADER)
    assert "mes notes" not in official_part and "[2] FICHIER JOINT (non officiel)" in attached_part


def test_generator_and_judge_caches_do_not_overwrite_each_other(tmp_path, monkeypatch):
    import eval.experiments as experiments

    monkeypatch.setattr(experiments, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    generator, judge = experiments.CachedLLM("gen"), experiments.CachedLLM("judge")
    for llm in (generator, judge):
        llm.client = SimpleNamespace(generate=lambda system, user, name=llm.model: f"{name}:{user}")
    generator.generate("s", "q1")
    judge.generate("s", "q1")
    generator.save()
    judge.save()  # ne doit pas effacer la reponse du generateur
    assert len(json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))) == 2
