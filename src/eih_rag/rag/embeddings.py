"""Embeddings multilingues de production et alternative legere de test."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Protocol


class EmbeddingUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Modele multilingue adapte au francais, charge uniquement au premier usage."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        # Les modeles E5 attendent des prefixes distincts pour requetes et passages.
        is_e5 = "e5" in model_name.lower()
        self.query_prefix = "query: " if is_e5 else ""
        self.passage_prefix = "passage: " if is_e5 else ""

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise EmbeddingUnavailable("sentence-transformers est requis pour les embeddings de production.") from error
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self._get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=16).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.passage_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self.query_prefix + text])[0]


class HashingEmbedder:
    """Embedder deterministe reserve aux tests et demonstrations hors ligne.

    Il n'est jamais le choix par defaut : le projet utilise normalement le modele
    SentenceTransformers multilingue configure dans ``.env``.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        counts = Counter(re.findall(r"[\w'-]+", text.lower(), flags=re.UNICODE))
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            position = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[position] += sign * count
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def build_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "sentence_transformers":
        return SentenceTransformerEmbedder(model_name)
    if backend == "hashing":
        return HashingEmbedder()
    raise ValueError("RAG_EMBEDDING_BACKEND doit etre 'sentence_transformers' ou 'hashing'.")
