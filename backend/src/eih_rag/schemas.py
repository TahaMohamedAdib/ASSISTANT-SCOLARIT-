"""Modeles Pydantic exposes par l'API REST."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChunkingOptions(BaseModel):
    strategy: Literal["fixed", "structural"] = "structural"
    chunk_size: int = Field(default=1200, ge=50, le=5000)
    overlap: int = Field(default=200, ge=0, le=2000)

    @model_validator(mode="after")
    def check_overlap(self) -> "ChunkingOptions":
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap doit etre strictement inferieur a chunk_size")
        return self


class IngestRequest(ChunkingOptions):
    pass


class IngestResponse(BaseModel):
    documents_indexed: int
    chunks_indexed: int
    strategy: ChunkingOptions


class SearchFilters(BaseModel):
    type: str | None = Field(default=None, description="Type exact de document, par exemple 'Guide pratique'.")


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=20)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La question ne peut pas etre vide.")
        return value


class Source(BaseModel):
    id: str
    chunk_id: str
    file: str
    reference: str | None = None
    date: str | None = None
    page: int
    section: str | None = None
    excerpt: str
    score: float


class SearchResponse(BaseModel):
    fragments: list[Source]


class AskRequest(SearchRequest):
    pass


class AskResponse(BaseModel):
    answer: str
    found: bool
    sources: list[Source]
    invalid_citations: list[int]
    latency_ms: int


class IndexedDocument(BaseModel):
    file: str
    reference: str | None = None
    type: str | None = None
    date: str | None = None
    version: str | None = None
    status: str | None = None
    page_count: int
    chunk_count: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    indexed_fragments: int
