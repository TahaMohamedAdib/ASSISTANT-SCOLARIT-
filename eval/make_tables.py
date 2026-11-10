"""Convertit eval/results/*.csv en tableaux Markdown (repris dans eval/RESULTS.md).

    python eval/make_tables.py > eval/results/tables.md
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def short(model: str) -> str:
    return model.split("/")[-1].replace("paraphrase-multilingual-", "").replace("multilingual-", "")


def retrieval_table() -> str:
    rows = list(csv.DictReader((RESULTS / "retrieval_experiments.csv").open(encoding="utf-8")))
    seen, lines = set(), [
        "| Expérience | Découpage | Embedding | Mode (poids dense) | Reranker | k | Recall@k | FullRecall@k | MRR | s/question |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        mode = row["mode"] + (f" ({row['dense_weight']})" if row["mode"] == "hybrid" else "")
        if row["query_expansion"] == "True":
            mode += " + expansion"
        rerank = short(row["reranker"]) if row["rerank"] == "True" else "—"
        lines.append(
            f"| {row['name']} | {row['strategy']} {row['chunk_size']}/{row['overlap']} | {short(row['embedding'])} | {mode} | {rerank} | {row['top_k']} "
            f"| {float(row['recall']):.3f} | {float(row['full_recall']):.3f} | {float(row['mrr']):.3f} | {float(row['sec_per_q']):.2f} |"
        )
    return "\n".join(lines)


def generation_table() -> str:
    path = RESULTS / "generation_experiments.csv"
    if not path.exists():
        return "(aucune evaluation de generation)"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    lines = [
        "| Expérience | Prompt | k | Exactitude (%) | Totalement correct (%) | Fidélité (%) | Refus corrects (%) | Refus à tort (%) | Citations invalides (%) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    categories: dict[str, dict[str, float]] = {}
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['prompt']} | {row['top_k']} | {float(row['correctness_pct']):.1f} | {float(row['fully_correct_pct']):.1f} "
            f"| {float(row['faithfulness_pct']):.1f} | {float(row['correct_refusal_pct']):.1f} | {float(row['false_refusal_pct']):.1f} | {float(row['invalid_citation_pct']):.1f} |"
        )
        categories[row["name"]] = json.loads(row["by_category_correctness_pct"])
    names = list(categories)
    cats = sorted({cat for values in categories.values() for cat in values})
    lines += ["", "Exactitude (%) par catégorie :", "", "| Catégorie | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for cat in cats:
        lines.append(f"| {cat} | " + " | ".join(f"{categories[name].get(cat, float('nan')):.0f}" for name in names) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    print("## Recherche\n")
    print(retrieval_table())
    print("\n## Génération\n")
    print(generation_table())
