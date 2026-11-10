import json
from collections import Counter
from pathlib import Path

from eval.run_eval import NO_ANSWER, answer_accuracy, load_questions


def test_evaluation_set_matches_required_distribution():
    questions = load_questions(Path("eval/questions.jsonl"))
    assert len(questions) == 20
    assert Counter(question["category"] for question in questions) == {
        "simple": 8,
        "synthese": 5,
        "version": 2,
        "hors_corpus": 5,
    }


def test_reproducible_accuracy_scoring():
    assert answer_accuracy(NO_ANSWER, expected_found=False, keywords=[]) == 2
    assert answer_accuracy("La réponse donne 18 semaines et 14 jours.", expected_found=True, keywords=["18 semaines", "14 jours"]) == 2
    assert answer_accuracy("La réponse donne 18 semaines.", expected_found=True, keywords=["18 semaines", "14 jours"]) == 1
