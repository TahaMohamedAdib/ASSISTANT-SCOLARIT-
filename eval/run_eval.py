"""Evaluation reproductible de la recherche et de la generation RAG.

Exemples:
    python eval/run_eval.py --api-url http://localhost:8000 --search-only --compare
    python eval/run_eval.py --api-url http://localhost:8000 --compare
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parent
NO_ANSWER = "Je ne trouve pas cette information dans les documents de l'École."


@dataclass(frozen=True)
class Configuration:
    strategy: str
    chunk_size: int
    overlap: int

    @property
    def label(self) -> str:
        return f"{self.strategy}-{self.chunk_size}-{self.overlap}"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value.lower()).strip()


def load_questions(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_configuration(value: str) -> Configuration:
    try:
        strategy, chunk_size, overlap = value.split(":")
        if strategy not in {"fixed", "structural"}:
            raise ValueError
        return Configuration(strategy, int(chunk_size), int(overlap))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Une configuration doit avoir la forme structural:500:100.") from error


def answer_accuracy(answer: str, expected_found: bool, keywords: list[str]) -> int:
    """Score strict mais reproductible : 0, 1 ou 2 selon les termes attendus."""
    if not expected_found:
        return 2 if answer.strip() == NO_ANSWER else 0
    if not keywords:
        return 0
    haystack = normalize(answer)
    matched = sum(normalize(keyword) in haystack for keyword in keywords)
    return 2 if matched == len(keywords) else 1 if matched else 0


def retrieval_metrics(references: list[str], expected_references: list[str]) -> tuple[float | None, float | None]:
    if not expected_references:
        return None, None
    rank = next((index + 1 for index, reference in enumerate(references) if reference in expected_references), None)
    return (1.0 if rank else 0.0), (1.0 / rank if rank else 0.0)


def evaluate_configuration(client: httpx.Client, config: Configuration, questions: list[dict[str, Any]], search_only: bool) -> dict[str, Any]:
    ingestion = client.post("/api/ingest", json={"strategy": config.strategy, "chunk_size": config.chunk_size, "overlap": config.overlap})
    ingestion.raise_for_status()

    rows: list[dict[str, Any]] = []
    for question in questions:
        search = client.post("/api/search", json={"question": question["question"], "top_k": 5, "filters": {"type": None}})
        search.raise_for_status()
        fragments = search.json()["fragments"]
        references = [fragment.get("reference") for fragment in fragments]
        hit, reciprocal_rank = retrieval_metrics(references, question["expected_references"])
        row: dict[str, Any] = {
            "id": question["id"],
            "category": question["category"],
            "retrieved_references": references,
            "hit_at_5": hit,
            "reciprocal_rank": reciprocal_rank,
        }
        if not search_only:
            response = client.post("/api/ask", json={"question": question["question"], "top_k": 5, "filters": {"type": None}})
            if response.status_code == 502:
                row["generation_error"] = response.json().get("detail", "LLM indisponible")
            else:
                response.raise_for_status()
                answer = response.json()
                row.update(
                    answer=answer["answer"],
                    found=answer["found"],
                    accuracy_0_to_2=answer_accuracy(answer["answer"], question["expected_found"], question["answer_keywords"]),
                    faithful=not answer["invalid_citations"] and (not answer["found"] or bool(re.findall(r"\[\d+\]", answer["answer"]))),
                    invalid_citations=answer["invalid_citations"],
                )
        rows.append(row)

    in_corpus = [row for row in rows if row["hit_at_5"] is not None]
    generated = [row for row in rows if "accuracy_0_to_2" in row]
    outside = [row for row, question in zip(rows, questions, strict=True) if not question["expected_found"] and "found" in row]
    return {
        "configuration": config.__dict__,
        "ingestion": ingestion.json(),
        "metrics": {
            "hit_at_5": statistics.fmean(row["hit_at_5"] for row in in_corpus),
            "mrr": statistics.fmean(row["reciprocal_rank"] for row in in_corpus),
            "answer_accuracy_mean_0_to_2": statistics.fmean(row["accuracy_0_to_2"] for row in generated) if generated else None,
            "faithfulness_rate": statistics.fmean(float(row["faithful"]) for row in generated) if generated else None,
            "correct_refusal_rate": statistics.fmean(float(not row["found"]) for row in outside) if outside else None,
            "false_refusal_rate": statistics.fmean(float(not row.get("found", True)) for row in generated if row["category"] != "hors_corpus") if generated else None,
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalue la recherche et les reponses de l'Assistant Scolarite.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--questions", type=Path, default=ROOT / "questions.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "results.json")
    parser.add_argument("--configs", default="structural:500:100,fixed:500:100", help="Liste separee par des virgules.")
    parser.add_argument("--compare", action="store_true", help="Evalue toutes les configurations ; sinon uniquement la premiere.")
    parser.add_argument("--search-only", action="store_true", help="Mesure seulement Hit@k et MRR, sans appeler le LLM.")
    parser.add_argument("--label", default="", help="Contexte du run, par exemple 'hashing-offline'.")
    args = parser.parse_args()
    questions = load_questions(args.questions)
    configurations = [parse_configuration(value.strip()) for value in args.configs.split(",")]
    if not args.compare:
        configurations = configurations[:1]

    try:
        with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=120.0) as client:
            results = [evaluate_configuration(client, config, questions, args.search_only) for config in configurations]
    except httpx.HTTPError as error:
        print(f"Echec de l'evaluation : {error}", file=sys.stderr)
        return 2

    payload = {"questions": len(questions), "search_only": args.search_only, "run_label": args.label or None, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        metrics = result["metrics"]
        print(f"{result['configuration']['strategy']}: Hit@5={metrics['hit_at_5']:.3f}, MRR={metrics['mrr']:.3f}")
    print(f"Rapport écrit : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
