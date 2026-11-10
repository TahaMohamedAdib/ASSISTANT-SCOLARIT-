"""Banc d'experiences RAG : recherche (local, gratuit) puis generation (Groq).

Recherche — pour chaque configuration (decoupage, embedding, mode, poids, reranker) :
    * Recall@k     : part des preuves attendues presentes dans le top-k ;
    * FullRecall@k : 1 si toutes les preuves sont presentes (questions multi-parties) ;
    * MRR          : rang du premier fragment contenant une preuve.
Generation — reponses produites par le pipeline complet, notees par un LLM juge :
    * correctness  : 0 (faux) / 1 (partiel) / 2 (correct) vs. reponse de reference ;
    * faithful     : la reponse ne contient que des affirmations soutenues par le contexte ;
    * refus corrects (hors corpus) et refus a tort (questions couvertes) ;
    * citations invalides (numero [n] hors des sources fournies).

Exemples :
    python eval/experiments.py retrieval --grid default
    python eval/experiments.py generate --config best --limit 81
Les resultats sont ajoutes a eval/results/*.csv ; les appels LLM sont mis en cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from eih_rag.chunking import create_chunks  # noqa: E402
from eih_rag.extraction import extract_pdf  # noqa: E402
from eih_rag.rag.embeddings import SentenceTransformerEmbedder  # noqa: E402
from eih_rag.rag.llm import OpenAICompatibleGenerator  # noqa: E402
from eih_rag.rag.prompting import NO_ANSWER, PROMPTS, build_user_prompt, invalid_citations  # noqa: E402
from eih_rag.rag.retrieval import CrossEncoderReranker, HybridRetriever, LLMQueryRewriter, RetrievalConfig  # noqa: E402
from eih_rag.rag.store import ChromaStore  # noqa: E402

RESULTS = ROOT / "eval" / "results"
CACHE_PATH = ROOT / "eval" / "results" / "llm_cache.json"


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class Experiment:
    name: str
    strategy: str = "structural"
    chunk_size: int = 500
    overlap: int = 100
    embedding: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    mode: str = "hybrid"
    dense_weight: float = 0.5
    candidate_k: int = 20
    rerank: bool = False
    reranker: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    query_expansion: bool = False
    top_k: int = 5
    prompt: str = "v2"
    llm: str = "openai/gpt-oss-120b"
    threshold: float = 0.0

    def retrieval_config(self) -> RetrievalConfig:
        return RetrievalConfig(
            mode=self.mode, dense_weight=self.dense_weight, candidate_k=self.candidate_k,
            rerank=self.rerank, rerank_candidates=self.candidate_k, query_expansion=self.query_expansion,
        )


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value.lower()).strip()


def load_testset(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- shared resources
_PAGES = None
_EMBEDDERS: dict[str, SentenceTransformerEmbedder] = {}
_STORES: dict[tuple, ChromaStore] = {}
_RERANKERS: dict[str, CrossEncoderReranker] = {}


def corpus_pages():
    global _PAGES
    if _PAGES is None:
        _PAGES = [extract_pdf(pdf) for pdf in sorted((ROOT / "corpus").glob("*.pdf"))]
    return _PAGES


def store_for(exp: Experiment) -> ChromaStore:
    key = (exp.strategy, exp.chunk_size, exp.overlap, exp.embedding)
    if key not in _STORES:
        embedder = _EMBEDDERS.setdefault(exp.embedding, SentenceTransformerEmbedder(exp.embedding))
        chunks = [chunk for metadata, pages in corpus_pages() for chunk in create_chunks(pages, metadata, exp.strategy, exp.chunk_size, exp.overlap)]
        store = ChromaStore(Path(tempfile.mkdtemp(prefix="eih_exp_")) / "chroma", "experiment_chunks", embedder)
        started = time.time()
        store.rebuild(chunks)
        print(f"  [index] {exp.strategy}:{exp.chunk_size}:{exp.overlap} {exp.embedding.split('/')[-1]} -> {len(chunks)} fragments ({time.time() - started:.0f}s)", flush=True)
        _STORES[key] = store
    return _STORES[key]


def retriever_for(exp: Experiment, generator=None) -> HybridRetriever:
    reranker = _RERANKERS.setdefault(exp.reranker, CrossEncoderReranker(exp.reranker)) if exp.rerank else None
    rewriter = LLMQueryRewriter(generator) if exp.query_expansion and generator else None
    return HybridRetriever(store_for(exp), exp.retrieval_config(), reranker=reranker, rewriter=rewriter)


# --------------------------------------------------------------------------- retrieval metrics
def evidence_metrics(hits, evidence: list[str]) -> dict[str, float]:
    texts = [normalize(hit.text) for hit in hits]
    # chaque preuve = liste de formulations equivalentes
    wanted = [[normalize(alt) for alt in (item if isinstance(item, list) else [item])] for item in evidence]
    found = [any(alt in text for alt in alts for text in texts) for alts in wanted]
    first = next((rank for rank, text in enumerate(texts, start=1) if any(alt in text for alts in wanted for alt in alts)), None)
    return {
        "recall": sum(found) / len(wanted),
        "full_recall": float(all(found)),
        "rr": 1.0 / first if first else 0.0,
    }


def run_retrieval(exp: Experiment, questions, generator=None) -> dict[str, Any]:
    retriever = retriever_for(exp, generator)
    rows, started = [], time.time()
    for question in questions:
        if not question["evidence"]:
            continue
        hits = retriever.search(question["question"], exp.top_k)
        rows.append({"id": question["id"], "category": question["category"], **evidence_metrics(hits, question["evidence"])})
    latency = (time.time() - started) / max(len(rows), 1)
    summary = {
        "recall": statistics.fmean(r["recall"] for r in rows),
        "full_recall": statistics.fmean(r["full_recall"] for r in rows),
        "mrr": statistics.fmean(r["rr"] for r in rows),
        "sec_per_q": latency,
    }
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row["full_recall"])
    summary["by_category_full_recall"] = {cat: statistics.fmean(vals) for cat, vals in sorted(by_category.items())}
    return {"summary": summary, "rows": rows}


# --------------------------------------------------------------------------- LLM with cache
class CachedLLM:
    def __init__(self, model: str) -> None:
        from dotenv import dotenv_values

        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = env.get("OPENAI_API_KEY") or env.get("GROQ_API_KEY") or ""
        if not key:
            raise SystemExit("OPENAI_API_KEY (cle Groq) manquante dans .env")
        self.model = model
        self.client = OpenAICompatibleGenerator(env.get("OPENAI_BASE_URL") or "https://api.groq.com/openai/v1", model, key)
        self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
        self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        key = hashlib.sha256(f"{self.model}\n{system_prompt}\n{user_prompt}".encode()).hexdigest()
        if key not in self.cache:
            self.cache[key] = self.client.generate(system_prompt, user_prompt)
            self.calls += 1
            if self.calls % 5 == 0:
                self.save()
        return self.cache[key]

    def save(self) -> None:
        # Generateur et juge partagent ce fichier : on fusionne avec le contenu actuel au lieu de
        # l'ecraser, sinon chaque instance efface les entrees ajoutees par l'autre.
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        on_disk = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
        self.cache = {**on_disk, **self.cache}
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_PATH)


JUDGE_PROMPT = """Tu es un evaluateur strict d'un assistant RAG de scolarite. On te donne la question, la reponse de reference,
les extraits fournis a l'assistant et la reponse de l'assistant. Reponds UNIQUEMENT par un objet JSON :
{"correctness": 0|1|2, "faithful": true|false, "refused": true|false, "reason": "<= 25 mots"}
- correctness : 2 si la reponse contient tous les elements essentiels de la reference sans erreur ;
  1 si partiellement correcte ou incomplete ; 0 si fausse, hors sujet, ou refus alors que la reference repond.
  Si la reference est un refus (information absente), 2 si l'assistant refuse ou indique clairement que l'information
  n'est pas dans les documents (il peut ajouter des informations connexes exactes), 0 s'il invente une reponse.
  Des details supplementaires exacts ne sont pas penalises ; une contradiction avec la reference l'est.
- faithful : true si chaque affirmation factuelle de la reponse est soutenue par les extraits (un refus est fidele).
- refused : true si l'assistant declare ne pas trouver l'information."""


def judge(llm: CachedLLM, question, answer: str, context: str) -> dict[str, Any]:
    user = (
        f"QUESTION:\n{question['question']}\n\nREPONSE DE REFERENCE:\n{question['expected_answer']}\n\n"
        f"EXTRAITS FOURNIS:\n{context}\n\nREPONSE DE L'ASSISTANT:\n{answer}"
    )
    raw = llm.generate(JUDGE_PROMPT, user)
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        verdict = {}
    return {
        "correctness": int(verdict.get("correctness", 0)),
        "faithful": bool(verdict.get("faithful", False)),
        "refused": bool(verdict.get("refused", False)),
        "judge_reason": str(verdict.get("reason", raw[:120])),
    }


def run_generation(exp: Experiment, questions, judge_model: str) -> dict[str, Any]:
    generator = CachedLLM(exp.llm)
    judge_llm = CachedLLM(judge_model)
    retriever = retriever_for(exp, generator)
    system_prompt = PROMPTS[exp.prompt]
    rows = []
    try:
        for index, question in enumerate(questions, start=1):
            hits = retriever.search(question["question"], exp.top_k)
            best = max((hit.relevance or 0.0) for hit in hits) if hits else 0.0
            user_prompt = build_user_prompt(question["question"], hits)
            if not hits or best < exp.threshold:
                answer = NO_ANSWER
            else:
                answer = generator.generate(system_prompt, user_prompt).strip()
            verdict = judge(judge_llm, question, answer, user_prompt)
            keywords = question["answer_keywords"]
            rows.append({
                "id": question["id"],
                "category": question["category"],
                "expected_found": question["expected_found"],
                "answer": answer,
                **verdict,
                "keyword_recall": (sum(normalize(k) in normalize(answer) for k in keywords) / len(keywords)) if keywords else None,
                "invalid_citations": invalid_citations(answer, len(hits)),
                "cited": bool(re.search(r"\[\d+\]", answer)),
                **(evidence_metrics(hits, question["evidence"]) if question["evidence"] else {}),
            })
            print(f"  {index:3d}/{len(questions)} {question['id']:10s} correctness={verdict['correctness']} faithful={verdict['faithful']}", flush=True)
    finally:
        generator.save()
        judge_llm.save()
    return {"summary": summarize_generation(rows), "rows": rows}


def summarize_generation(rows) -> dict[str, Any]:
    answerable = [r for r in rows if r["expected_found"]]
    outside = [r for r in rows if not r["expected_found"]]
    summary = {
        "correctness_pct": 100 * statistics.fmean(r["correctness"] for r in rows) / 2,
        "fully_correct_pct": 100 * statistics.fmean(r["correctness"] == 2 for r in rows),
        "faithfulness_pct": 100 * statistics.fmean(r["faithful"] for r in rows),
        "correct_refusal_pct": 100 * statistics.fmean(r["refused"] for r in outside) if outside else None,
        "false_refusal_pct": 100 * statistics.fmean(r["refused"] and r["correctness"] == 0 for r in answerable) if answerable else None,
        "citation_rate_pct": 100 * statistics.fmean(r["cited"] for r in answerable) if answerable else None,
        "invalid_citation_pct": 100 * statistics.fmean(bool(r["invalid_citations"]) for r in rows),
    }
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row["correctness"])
    summary["by_category_correctness_pct"] = {cat: 100 * statistics.fmean(v) / 2 for cat, v in sorted(by_category.items())}
    return summary


# --------------------------------------------------------------------------- grids
BASE = Experiment(name="base")
EMB_MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMB_E5 = "intfloat/multilingual-e5-base"
EMB_BGE = "BAAI/bge-m3"
RR_MINI = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RR_BGE = "BAAI/bge-reranker-v2-m3"


def grid(name: str) -> list[Experiment]:
    if name == "baseline":
        return [replace(BASE, name="baseline_dense_fixed", strategy="fixed", mode="dense"), replace(BASE, name="baseline_dense_structural", mode="dense")]
    if name == "chunking":
        out = []
        for strategy in ("fixed", "structural"):
            for size, overlap in ((300, 50), (500, 100), (800, 150), (1200, 200)):
                out.append(replace(BASE, name=f"chunk_{strategy}_{size}_{overlap}", strategy=strategy, chunk_size=size, overlap=overlap))
        return out
    if name == "mode":
        return [replace(BASE, name=f"mode_{mode}", mode=mode) for mode in ("dense", "bm25", "hybrid")] + [
            replace(BASE, name=f"weight_{w}", dense_weight=w) for w in (0.3, 0.7)
        ]
    if name == "embedding":
        return [replace(BASE, name=f"emb_{m.split('/')[-1]}", embedding=m, mode=mode) for m in (EMB_MINILM, EMB_E5, EMB_BGE) for mode in ("dense", "hybrid")]
    if name == "topk":
        return [replace(BASE, name=f"topk_{k}", top_k=k) for k in (3, 5, 8, 10)]
    if name == "rerank":
        return [replace(BASE, name="rerank_off"), replace(BASE, name="rerank_mmarco", rerank=True, reranker=RR_MINI), replace(BASE, name="rerank_bge", rerank=True, reranker=RR_BGE)]
    raise SystemExit(f"grille inconnue : {name}")


def parse_overrides(base: Experiment, items: list[str]) -> Experiment:
    """--set cle=valeur pour composer une configuration (ex. --set chunk_size=800 rerank=true)."""
    values = {}
    for item in items:
        key, _, raw = item.partition("=")
        current = getattr(base, key)
        values[key] = raw.lower() in ("1", "true", "yes") if isinstance(current, bool) else type(current)(raw)
    return replace(base, **values)


# --------------------------------------------------------------------------- output
def append_csv(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in record.items()}
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat))
        if not exists:
            writer.writeheader()
        writer.writerow(flat)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", choices=("retrieval", "generate"))
    parser.add_argument("--grid", help="baseline | chunking | mode | embedding | topk | rerank")
    parser.add_argument("--name", default="custom")
    parser.add_argument("--set", nargs="*", default=[], help="surcharges cle=valeur de la configuration")
    parser.add_argument("--testset", type=Path, default=ROOT / "eval" / "testset.jsonl")
    parser.add_argument("--ids", default="", help="sous-ensemble d'identifiants separes par des virgules")
    parser.add_argument("--judge", default="qwen/qwen3.8-27b")
    args = parser.parse_args()

    questions = load_testset(args.testset)
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    experiments = grid(args.grid) if args.grid else [parse_overrides(replace(BASE, name=args.name), args.set)]
    stamp = time.strftime("%Y-%m-%d %H:%M")

    for exp in experiments:
        print(f"== {exp.name}", flush=True)
        if args.task == "retrieval":
            generator = CachedLLM(exp.llm) if exp.query_expansion else None
            result = run_retrieval(exp, questions, generator)
            if generator:
                generator.save()
            s = result["summary"]
            print(f"   Recall@{exp.top_k}={s['recall']:.3f} FullRecall@{exp.top_k}={s['full_recall']:.3f} MRR={s['mrr']:.3f} ({s['sec_per_q']:.2f}s/q)", flush=True)
            append_csv(RESULTS / "retrieval_experiments.csv", {"timestamp": stamp, **asdict(exp), **s})
        else:
            result = run_generation(exp, questions, args.judge)
            s = result["summary"]
            print(json.dumps(s, indent=1, ensure_ascii=False), flush=True)
            append_csv(RESULTS / "generation_experiments.csv", {"timestamp": stamp, "questions": len(questions), **asdict(exp), "judge": args.judge, **s})
            details = RESULTS / f"generation_{exp.name}.json"
            details.write_text(json.dumps({"experiment": asdict(exp), **result}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
