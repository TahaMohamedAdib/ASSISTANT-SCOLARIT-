"""Recherche hybride : dense (Chroma) + lexicale (BM25), fusion RRF, reranking.

Pipeline d'une question :
    1. (optionnel) reformulation en sous-requetes par le LLM ;
    2. pour chaque requete : top-N dense (Chroma) et top-N BM25 ;
    3. fusion Reciprocal Rank Fusion ponderee (poids dense / BM25) ;
    4. (optionnel) reranking des candidats par un cross-encoder multilingue ;
    5. top-k final. Chaque fragment garde ``relevance`` (score absolu dans
       [0, 1]) utilise par le seuil de refus.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np

from .store import RetrievedChunk


# Mots vides francais : retires uniquement pour BM25.
FRENCH_STOPWORDS = frozenset(
    """a afin ai au aux avec ce ces cet cette d da dans de des du elle en et etre
    eu il ils je l la le les leur leurs lui ma mais me meme mes moi mon n ne nos
    notre nous on ou par pas pour qu que quel quelle quelles quels qui sa se ses
    si son sur ta te tes toi ton tu un une vos votre vous y est sont a-t-il
    peut puis-je faut-il doit dois-je comment combien quand quoi ete fait""".split()
)


def tokenize(text: str) -> list[str]:
    """Minuscules, sans accents, sans mots vides, pluriel simple retire."""
    ascii_text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+(?:/[0-9]+)?", ascii_text)
    result = []
    for token in tokens:
        if token in FRENCH_STOPWORDS or (len(token) == 1 and not token.isdigit()):
            continue
        if len(token) > 4 and token.endswith(("s", "x")) and not token.isdigit():
            token = token[:-1]
        result.append(token)
    return result


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Cross-encoder SentenceTransformers ; scores ramenes dans [0, 1]."""

    def __init__(self, model_name: str, max_length: int = 512) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self._model = None

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, max_length=self.max_length)
        scores = np.asarray(self._model.predict([(query, passage) for passage in passages], show_progress_bar=False), dtype=float)
        if scores.min() < 0 or scores.max() > 1:  # logits bruts -> probabilite
            scores = 1.0 / (1.0 + np.exp(-scores))
        return scores.tolist()


class QueryRewriter(Protocol):
    def rewrite(self, question: str) -> list[str]: ...


REWRITE_PROMPT = """Tu prepares la recherche documentaire d'un assistant de scolarite d'ecole d'ingenieurs.
Reecris la question de l'etudiant en 1 a 3 requetes de recherche courtes, en francais, autonomes et precises.
- Si la question comporte plusieurs parties, fais une requete par partie.
- Remplace les formulations vagues par les termes administratifs probables (ex. "rattrapage", "PFE", "convention de stage").
- N'invente aucune information et ne reponds pas a la question.
Reponds uniquement par un tableau JSON de chaines, par exemple ["requete 1", "requete 2"]."""


class LLMQueryRewriter:
    """Expansion de requete par le LLM ; en cas d'echec, la question seule est utilisee."""

    def __init__(self, generator) -> None:
        self.generator = generator

    def rewrite(self, question: str) -> list[str]:
        try:
            raw = self.generator.generate(REWRITE_PROMPT, question)
            match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
            queries = json.loads(match.group(0)) if match else []
            return [str(query).strip() for query in queries if str(query).strip()][:3]
        except Exception:  # l'expansion est une amelioration, jamais un point de rupture
            return []


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "hybrid"  # dense | bm25 | hybrid
    dense_weight: float = 0.5  # poids du dense dans la fusion (BM25 = 1 - poids)
    candidate_k: int = 20  # candidats par requete et par methode
    rrf_k: int = 60
    rerank: bool = True
    rerank_candidates: int = 20
    query_expansion: bool = False


class HybridRetriever:
    def __init__(self, store, config: RetrievalConfig, reranker: Reranker | None = None, rewriter: QueryRewriter | None = None) -> None:
        self.store = store
        self.config = config
        self.reranker = reranker
        self.rewriter = rewriter
        self._corpus_version: int | None = None
        self._chunks: list[RetrievedChunk] = []
        self._embeddings: np.ndarray | None = None
        self._bm25 = None

    # ----- index lexical et cache, reconstruits apres chaque ingestion -----
    def _ensure_corpus(self) -> None:
        version = getattr(self.store, "version", 0)
        if self._bm25 is not None and version == self._corpus_version:
            return
        from rank_bm25 import BM25Okapi

        self._chunks, embeddings = self.store.all_chunks()
        self._embeddings = np.asarray(embeddings, dtype=float) if len(embeddings) else None
        corpus = [tokenize(self._index_text(chunk)) or ["_vide_"] for chunk in self._chunks]
        self._token_sets = [set(tokens) for tokens in corpus]
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._corpus_version = version

    @staticmethod
    def _index_text(chunk: RetrievedChunk) -> str:
        header = " > ".join(part for part in (chunk.title, chunk.section_path) if part)
        return f"{header}\n{chunk.text}" if header else chunk.text

    def _bm25_search(self, query: str, limit: int, document_type: str | None) -> list[str]:
        if self._bm25 is None:
            return []
        query_tokens = set(tokenize(query))
        scores = self._bm25.get_scores(list(query_tokens))
        order = np.argsort(-scores)
        ids = []
        for index in order:
            # L'IDF BM25 peut etre <= 0 pour un terme tres frequent : on garde
            # tout fragment partageant au moins un terme avec la requete.
            if not query_tokens & self._token_sets[index]:
                continue
            chunk = self._chunks[index]
            if document_type and getattr(chunk, "document_type", None) not in (None, document_type):
                continue
            ids.append(chunk.id)
            if len(ids) >= limit:
                break
        return ids

    def _cosine(self, query: str) -> dict[str, float]:
        """Similarite dense de la question avec chaque fragment (score absolu)."""
        if self._embeddings is None:
            return {}
        query_vector = np.asarray(self.store.embedder.embed_query(query), dtype=float)
        similarities = self._embeddings @ query_vector
        return {chunk.id: float(value) for chunk, value in zip(self._chunks, similarities)}

    # ----- recherche -----
    def search(self, question: str, top_k: int, document_type: str | None = None) -> list[RetrievedChunk]:
        self._ensure_corpus()
        if not self._chunks:
            return []
        cfg = self.config
        queries = [question]
        if cfg.query_expansion and self.rewriter is not None:
            queries += [query for query in self.rewriter.rewrite(question) if query.lower() != question.lower()]

        fused: dict[str, float] = {}
        methods: dict[str, set[str]] = {}

        def add(ranked_ids: list[str], weight: float, method: str) -> None:
            for rank, chunk_id in enumerate(ranked_ids, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + weight / (cfg.rrf_k + rank)
                methods.setdefault(chunk_id, set()).add(method)

        for query in queries:
            if cfg.mode in ("dense", "hybrid"):
                dense_ids = [hit.id for hit in self.store.search(query, cfg.candidate_k, document_type)]
                add(dense_ids, cfg.dense_weight if cfg.mode == "hybrid" else 1.0, "dense")
            if cfg.mode in ("bm25", "hybrid"):
                add(self._bm25_search(query, cfg.candidate_k, document_type), (1.0 - cfg.dense_weight) if cfg.mode == "hybrid" else 1.0, "bm25")

        by_id = {chunk.id: chunk for chunk in self._chunks}
        ranked = sorted(fused, key=fused.get, reverse=True)
        cosine = self._cosine(question)

        if cfg.rerank and self.reranker is not None:
            candidates = ranked[: cfg.rerank_candidates]
            scores = self.reranker.score(question, [self._index_text(by_id[cid]) for cid in candidates])
            ordered = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)[:top_k]
            return [
                replace(by_id[cid], score=round(float(score), 4), relevance=round(float(score), 4), methods=tuple(sorted(methods.get(cid, ()))) + ("rerank",))
                for cid, score in ordered
            ]

        return [
            replace(by_id[cid], score=round(fused[cid], 5), relevance=round(cosine.get(cid, 0.0), 4), methods=tuple(sorted(methods.get(cid, ()))))
            for cid in ranked[:top_k]
        ]
