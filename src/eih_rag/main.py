"""Application FastAPI de l'Assistant Scolarite EIH."""

from __future__ import annotations

from fastapi import Body, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .rag.llm import LLMUnavailable
from .rag.service import (
    DocumentConflict, DocumentError, DocumentNotFound, DocumentTooLarge,
    InvalidDocumentName, OfficialDocument, RagService, UnsupportedDocument,
)
from .rag.store import StoreUnavailable
from .schemas import AskRequest, AskResponse, HealthResponse, IndexedDocument, IngestRequest, IngestResponse, SearchRequest, SearchResponse


DOCUMENT_ERROR_STATUS = {
    InvalidDocumentName: 400,
    OfficialDocument: 403,
    DocumentNotFound: 404,
    DocumentConflict: 409,
    DocumentTooLarge: 413,
    UnsupportedDocument: 415,
}


class UploadBodyLimit:
    """Borne la requete avant que le parseur multipart ne la stocke sur disque."""

    def __init__(self, app: ASGIApp, max_upload_bytes: int) -> None:
        self.app = app
        # Laisser de la place pour les en-tetes et separateurs multipart.
        self.max_body_bytes = max_upload_bytes + 64 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        path = scope["path"].rstrip("/")
        root = scope.get("root_path", "").rstrip("/")
        if path not in {"/api/documents/upload", f"{root}/api/documents/upload"}:
            await self.app(scope, receive, send)
            return

        size = 0

        async def limited_receive() -> Message:
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_body_bytes:
                    raise HTTPException(status_code=413, detail="Requete de televersement trop volumineuse.")
            return message

        await self.app(scope, limited_receive, send)


def create_app(settings: Settings | None = None, service: RagService | None = None) -> FastAPI:
    settings = settings or (service.settings if service is not None else Settings())
    service = service or RagService(settings)
    app = FastAPI(title=settings.app_name, version="1.0.0", description="API RAG fondee sur le corpus EIH et les PDF televerses.")
    app.add_middleware(UploadBodyLimit, max_upload_bytes=service.settings.max_upload_bytes)
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
            return HealthResponse(status="ok", indexed_fragments=service.indexed_chunk_count())
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/ingest", response_model=IngestResponse, tags=["corpus"])
    def ingest(payload: IngestRequest = Body(default=IngestRequest())) -> IngestResponse:
        try:
            return service.ingest(payload)
        except (StoreUnavailable, ValueError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/api/documents", response_model=list[IndexedDocument], tags=["corpus"])
    def documents() -> list[IndexedDocument]:
        try:
            return service.documents()
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/documents/upload", response_model=IndexedDocument, status_code=201, tags=["corpus"])
    def upload_document(file: UploadFile = File(...)) -> IndexedDocument:
        try:
            if file.size is not None and file.size > service.settings.max_upload_bytes:
                raise DocumentTooLarge(f"Le fichier depasse la limite de {service.settings.max_upload_bytes} octets.")
            return service.upload_document(file.filename or "", file.file)
        except DocumentError as error:
            raise HTTPException(status_code=DOCUMENT_ERROR_STATUS[type(error)], detail=str(error)) from error
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.delete("/api/documents/{filename}", status_code=204, tags=["corpus"])
    def delete_document(filename: str) -> Response:
        try:
            service.delete_document(filename)
        except DocumentError as error:
            raise HTTPException(status_code=DOCUMENT_ERROR_STATUS[type(error)], detail=str(error)) from error
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return Response(status_code=204)

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
