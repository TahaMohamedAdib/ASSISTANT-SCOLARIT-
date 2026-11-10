"""Application FastAPI de l'Assistant Scolarite EIH."""

from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .rag.llm import LLMUnavailable
from .rag.service import RagService
from .rag.store import StoreUnavailable
from .schemas import AskRequest, AskResponse, HealthResponse, IndexedDocument, IngestRequest, IngestResponse, SearchRequest, SearchResponse


def create_app(settings: Settings | None = None, service: RagService | None = None) -> FastAPI:
    settings = settings or Settings()
    service = service or RagService(settings)
    app = FastAPI(title=settings.app_name, version="1.0.0", description="API RAG fondee exclusivement sur les documents officiels EIH.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse, tags=["service"])
    def health() -> HealthResponse:
        try:
            return HealthResponse(status="ok", indexed_fragments=service.store.count())
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/ingest", response_model=IngestResponse, tags=["corpus"])
    def ingest(payload: IngestRequest = Body(default=IngestRequest())) -> IngestResponse:
        try:
            return service.ingest(payload)
        except (StoreUnavailable, ValueError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/api/documents", response_model=list[IndexedDocument], tags=["corpus"])
    def documents() -> list[dict]:
        try:
            return service.documents()
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/search", response_model=SearchResponse, tags=["recherche"])
    def search(payload: SearchRequest) -> SearchResponse:
        try:
            result = service.search(payload)
            return SearchResponse(fragments=result.fragments)
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/ask", response_model=AskResponse, tags=["generation"])
    def ask(payload: AskRequest) -> AskResponse:
        try:
            return service.ask(payload)
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LLMUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    return app


app = create_app()
