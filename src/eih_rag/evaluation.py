"""Evaluation declenchee depuis la page Admin, sur l'index actif.

* Recherche (rapide, sans LLM) : Recall@k, FullRecall@k, MRR au niveau du passage
  sur ``eval/testset.jsonl`` (preuves verbatim).
* Generation (optionnelle, consomme le quota LLM) : un echantillon de questions
  passe par le pipeline complet ; un LLM juge note l'exactitude (0/1/2).
Le banc complet et ses grilles restent dans ``eval/experiments.py``.
"""

from __future__ import annotations

import csv
import json
import random
import re
import statistics
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .db import Database, new_id, now
from .rag.llm import strip_thinking
from .rag.prompting import NO_ANSWER, SYSTEM_PROMPT, build_user_prompt, is_refusal

TESTSET = PROJECT_ROOT / "eval" / "testset.jsonl"
OFFLINE_RESULTS = PROJECT_ROOT / "eval" / "results" / "generation_experiments.csv"

JUDGE_PROMPT = """Tu evalues un assistant RAG. Compare la reponse de l'assistant a la reponse de reference.
Reponds UNIQUEMENT par un JSON {"correctness": 0|1|2}. 2 = tous les elements essentiels sans erreur ;
1 = partiel ; 0 = faux ou refus injustifie. Si la reference est un refus, 2 si l'assistant refuse, sinon 0."""


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value.lower()).strip()


def evidence_metrics(texts: list[str], evidence: list) -> dict[str, float]:
    texts = [normalize(text) for text in texts]
    wanted = [[normalize(alt) for alt in (item if isinstance(item, list) else [item])] for item in evidence]
    found = [any(alt in text for alt in alts for text in texts) for alts in wanted]
    first = next((rank for rank, text in enumerate(texts, start=1) if any(alt in text for alts in wanted for alt in alts)), None)
    return {"recall": sum(found) / len(wanted), "full_recall": float(all(found)), "rr": 1.0 / first if first else 0.0}


def load_testset(path: Path = TESTSET) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class EvaluationService:
    def __init__(self, db: Database, rag, judge) -> None:
        self.db = db
        self.rag = rag
        self.judge = judge
        self._lock = threading.Lock()

    def start(self, mode: str = "retrieval", sample: int = 10, top_k: int = 6, background: bool = True) -> str:
        run_id = new_id()
        self.db.insert("eval_runs", {"id": run_id, "status": "running", "mode": mode, "started_at": now()})
        target = lambda: self._run(run_id, mode, sample, top_k)  # noqa: E731
        if background:
            threading.Thread(target=target, daemon=True, name=f"eval-{run_id}").start()
        else:
            target()
        return run_id

    def _run(self, run_id: str, mode: str, sample: int, top_k: int) -> None:
        with self._lock:
            try:
                questions = load_testset()
                rows = []
                for question in questions:
                    if not question["evidence"]:
                        continue
                    hits = self.rag.search_hits(question["question"], top_k, None)
                    rows.append({"category": question["category"], **evidence_metrics([hit.text for hit in hits], question["evidence"])})
                by_category = defaultdict(list)
                for row in rows:
                    by_category[row["category"]].append(row["full_recall"])
                summary: dict[str, Any] = {
                    "questions": len(rows), "top_k": top_k,
                    "recall_at_k": statistics.fmean(r["recall"] for r in rows),
                    "full_recall_at_k": statistics.fmean(r["full_recall"] for r in rows),
                    "mrr": statistics.fmean(r["rr"] for r in rows),
                    "by_category_full_recall": {k: statistics.fmean(v) for k, v in sorted(by_category.items())},
                }
                if mode == "full":
                    summary["generation"] = self._generation(random.Random(0).sample(questions, min(sample, len(questions))), top_k)
                self.db.update("eval_runs", run_id, {"status": "done", "summary": json.dumps(summary, ensure_ascii=False), "finished_at": now()})
            except Exception as error:  # visible dans l'interface
                self.db.update("eval_runs", run_id, {"status": "failed", "error": str(error)[:500], "finished_at": now()})

    def _generation(self, questions: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
        scores = []
        for question in questions:
            hits = self.rag.search_hits(question["question"], top_k, None)
            answer = self.rag.generator.generate(SYSTEM_PROMPT, build_user_prompt(question["question"], hits)).strip()
            raw = strip_thinking(self.judge.generate(JUDGE_PROMPT, f"QUESTION: {question['question']}\nREFERENCE: {question['expected_answer']}\nASSISTANT: {answer}"))
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            try:
                score = int(json.loads(match.group(0)).get("correctness", 0)) if match else 0
            except (ValueError, json.JSONDecodeError):
                score = 0
            if not question["expected_found"]:
                score = 2 if is_refusal(answer) or NO_ANSWER in answer else score
            scores.append(score)
        return {
            "sample": len(questions),
            "answer_accuracy_pct": 100 * statistics.fmean(scores) / 2 if scores else None,
            "fully_correct_pct": 100 * statistics.fmean(s == 2 for s in scores) if scores else None,
        }

    def runs(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?", (limit,))
        for row in rows:
            row["summary"] = json.loads(row["summary"]) if row["summary"] else None
        return rows

    @staticmethod
    def offline_results() -> list[dict[str, Any]]:
        """Resultats du banc complet (81 questions, eval/experiments.py), s'ils existent."""
        if not OFFLINE_RESULTS.exists():
            return []
        keep = ("name", "questions", "prompt", "top_k", "correctness_pct", "fully_correct_pct", "faithfulness_pct", "correct_refusal_pct", "false_refusal_pct")
        with OFFLINE_RESULTS.open(encoding="utf-8") as handle:
            return [{key: row.get(key) for key in keep} for row in csv.DictReader(handle)]
