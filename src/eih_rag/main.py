"""Application FastAPI de l'Assistant Scolarite EIH.

Routes historiques (conservees) : /api/health, /api/ingest, /api/documents,
/api/search, /api/ask. Routes v2 : chat en flux, conversations, televersement
et cycle de vie des documents, retours, administration, evaluation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import AdminAuth
from .chat import ChatService
from .config import Settings
from .db import Database
from .documents import DOC_TYPES, DocumentConflict, DocumentService
from .evaluation import EvaluationService
from .loaders import ALLOWED_EXTENSIONS, UploadRejected
from .rag.llm import LLMQuotaExceeded, LLMUnavailable
from .rag.service import RagService
from .rag.store import StoreUnavailable
from .schemas import AskRequest, AskResponse, HealthResponse, IngestRequest, SearchRequest, SearchResponse


# ---------------------------------------------------------------------- schemas v2
class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(default="", max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=15)
    doc_type: str | None = None
    regenerate: bool = False


class ConversationCreate(BaseModel):
    title: str = Field(default="Nouvelle conversation", max_length=120)


class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class EvalRequest(BaseModel):
    mode: Literal["retrieval", "full"] = "retrieval"
    sample: int = Field(default=10, ge=1, le=81)
    top_k: int = Field(default=6, ge=1, le=15)


def create_app(
    settings: Settings | None = None,
    service: RagService | None = None,
    db: Database | None = None,
    background: bool = True,
    sync_corpus: bool | None = None,
) -> FastAPI:
    settings = settings or Settings()
    service = service or RagService(settings)
    db = db or Database(settings.db_path)
    auth = AdminAuth(settings.admin_password, settings.auth_secret)
    require_admin = auth.dependency()
    documents = DocumentService(settings, db, service.store, background=background)
    chat = ChatService(settings, db, service)
    evaluation = EvaluationService(db, service, chat.aux)
    if sync_corpus is None:
        sync_corpus = hasattr(service.store, "document_chunk_counts")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if sync_corpus:
            documents.sync_base_corpus()  # enregistre les 7 PDF et indexe uniquement ce qui manque
        yield
        documents.shutdown()

    app = FastAPI(title=settings.app_name, version="2.0.0", description="API RAG fondee exclusivement sur les documents officiels EIH.", lifespan=lifespan)
    app.state.documents = documents
    app.state.chat = chat
    app.state.db = db
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def conflict(error: DocumentConflict) -> HTTPException:
        status = 404 if error.code == "not_found" else 409
        return HTTPException(status_code=status, detail={"code": error.code, "message": str(error), "document_id": error.document_id})

    # ------------------------------------------------------------------ service
    @app.get("/api/health", response_model=HealthResponse, tags=["service"])
    def health() -> HealthResponse:
        try:
            return HealthResponse(status="ok", indexed_fragments=service.store.count())
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/api/config", tags=["service"])
    def config() -> dict:
        return {
            "contact_email": settings.contact_email, "contact_phone": settings.contact_phone,
            "max_upload_mb": settings.max_upload_mb, "allowed_extensions": list(ALLOWED_EXTENSIONS),
            "doc_types": list(DOC_TYPES), "require_review": settings.require_review,
            "admin_enabled": auth.enabled, "default_top_k": settings.default_top_k,
        }

    @app.get("/api/stats", tags=["corpus"])
    def stats() -> dict:
        try:
            return documents.stats()
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    # ------------------------------------------------------------------ auth
    @app.post("/api/auth/login", tags=["auth"])
    def login(payload: LoginRequest) -> dict:
        return {"token": auth.login(payload.password), "role": "admin"}

    @app.get("/api/auth/me", tags=["auth"])
    def me(authorization: str | None = Header(default=None)) -> dict:
        token = authorization.removeprefix("Bearer ").strip() if authorization else None
        return {"role": auth.role(token), "admin_enabled": auth.enabled}

    # ------------------------------------------------------------------ documents
    @app.post("/api/ingest", tags=["corpus"])
    def ingest(payload: IngestRequest = Body(default=IngestRequest()), _: str = Depends(require_admin)) -> dict:
        """Reindexe tous les documents actifs (incrementalement, document par document)."""
        try:
            jobs = documents.reindex_all()
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"jobs": jobs, "documents_queued": len(jobs)}

    @app.get("/api/documents", tags=["corpus"])
    def list_documents(history: bool = False) -> list[dict]:
        return documents.list(include_history=history)

    @app.post("/api/documents", status_code=202, tags=["corpus"])
    async def upload_document(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        doc_type: str = Form(default="Autre"),
        department: str = Form(default=""),
        effective_date: str = Form(default=""),
        version: str = Form(default=""),
        official: bool = Form(default=True),
        replace_id: str = Form(default=""),
        allow_same_title: bool = Form(default=False),
        _: str = Depends(require_admin),
    ) -> dict:
        limit = settings.max_upload_mb * 1024 * 1024
        content = await file.read(limit + 1)
        try:
            return documents.upload(
                file.filename or "document",
                content,
                {"title": title, "doc_type": doc_type, "department": department, "effective_date": effective_date, "version": version, "official": official},
                replace_id=replace_id or None,
                allow_same_title=allow_same_title,
            )
        except UploadRejected as error:
            raise HTTPException(status_code=422, detail={"code": "rejected", "message": str(error)}) from error
        except DocumentConflict as error:
            raise conflict(error) from error

    @app.get("/api/documents/{document_id}/file", tags=["corpus"])
    def document_file(document_id: str):
        try:
            path = documents.file_path(document_id)
        except DocumentConflict as error:
            raise conflict(error) from error
        allowed = [Path(settings.corpus_dir).resolve(), Path(settings.uploads_dir).resolve()]
        if not path.is_file() or not any(path.resolve().is_relative_to(root) for root in allowed):
            raise HTTPException(status_code=404, detail="Fichier introuvable.")
        media = "application/pdf" if path.suffix.lower() == ".pdf" else None
        return FileResponse(path, media_type=media, filename=path.name, content_disposition_type="inline" if media else "attachment")

    @app.get("/api/documents/{document_id}/chunks", tags=["corpus"])
    def document_chunks(document_id: str) -> list[dict]:
        return [
            {"id": chunk.id, "page": chunk.page, "section": chunk.section_path or chunk.section, "text": chunk.text}
            for chunk in service.store.document_chunks(document_id)
        ]

    @app.delete("/api/documents/{document_id}", status_code=204, tags=["corpus"])
    def delete_document(document_id: str, _: str = Depends(require_admin)) -> None:
        try:
            documents.delete(document_id)
        except DocumentConflict as error:
            raise conflict(error) from error

    @app.post("/api/documents/{document_id}/reindex", status_code=202, tags=["corpus"])
    def reindex_document(document_id: str, _: str = Depends(require_admin)) -> dict:
        try:
            return {"job_id": documents.reindex(document_id)}
        except DocumentConflict as error:
            raise conflict(error) from error

    @app.post("/api/documents/{document_id}/approve", status_code=202, tags=["corpus"])
    def approve_document(document_id: str, _: str = Depends(require_admin)) -> dict:
        try:
            return {"job_id": documents.approve(document_id)}
        except DocumentConflict as error:
            raise conflict(error) from error

    @app.post("/api/documents/reindex-all", status_code=202, tags=["corpus"])
    def reindex_all(_: str = Depends(require_admin)) -> dict:
        return {"jobs": documents.reindex_all()}

    @app.get("/api/ingestion/{job_id}", tags=["corpus"])
    def ingestion_status(job_id: str) -> dict:
        job = documents.job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Tâche introuvable.")
        return job

    # ------------------------------------------------------------------ recherche
    @app.post("/api/search", response_model=SearchResponse, tags=["recherche"])
    def search(payload: SearchRequest) -> SearchResponse:
        try:
            return SearchResponse(fragments=service.search(payload).fragments)
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/ask", response_model=AskResponse, tags=["generation"])
    def ask(payload: AskRequest) -> AskResponse:
        try:
            return service.ask(payload)
        except StoreUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LLMQuotaExceeded as error:
            headers = {"Retry-After": str(int(error.retry_after))} if error.retry_after else None
            raise HTTPException(status_code=429, detail=str(error), headers=headers) from error
        except LLMUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    # ------------------------------------------------------------------ chat
    @app.post("/api/chat", tags=["generation"])
    def chat_stream(payload: ChatRequest) -> StreamingResponse:
        if not payload.regenerate and not payload.message.strip():
            raise HTTPException(status_code=422, detail="La question ne peut pas être vide.")
        stream = chat.stream(payload.conversation_id, payload.message.strip(), payload.top_k, payload.doc_type, payload.regenerate)
        return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/conversations", tags=["conversations"])
    def list_conversations(q: str = "") -> list[dict]:
        return chat.list_conversations(q.strip())

    @app.post("/api/conversations", status_code=201, tags=["conversations"])
    def create_conversation(payload: ConversationCreate = Body(default=ConversationCreate())) -> dict:
        return chat.create_conversation(payload.title)

    @app.get("/api/conversations/{conversation_id}", tags=["conversations"])
    def get_conversation(conversation_id: str) -> dict:
        conversation = chat.conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        return conversation

    @app.patch("/api/conversations/{conversation_id}", tags=["conversations"])
    def rename_conversation(conversation_id: str, payload: ConversationPatch) -> dict:
        if not db.conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        chat.rename(conversation_id, payload.title)
        return db.conversation(conversation_id)

    @app.delete("/api/conversations/{conversation_id}", status_code=204, tags=["conversations"])
    def delete_conversation(conversation_id: str) -> None:
        chat.delete(conversation_id)

    @app.post("/api/conversations/{conversation_id}/attachments", status_code=201, tags=["conversations"])
    async def attach(conversation_id: str, file: UploadFile = File(...)) -> dict:
        if not db.conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        try:
            return chat.attach(conversation_id, file.filename or "fichier", content)
        except (UploadRejected, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "rejected", "message": str(error)}) from error

    # ------------------------------------------------------------------ retours et administration
    @app.post("/api/feedback", status_code=201, tags=["retours"])
    def feedback(payload: FeedbackRequest) -> dict:
        try:
            chat.feedback(payload.message_id, payload.rating, payload.comment)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Message introuvable.") from error
        return {"ok": True}

    @app.get("/api/admin/feedback", tags=["administration"])
    def admin_feedback(_: str = Depends(require_admin)) -> dict:
        return chat.feedback_summary()

    @app.get("/api/admin/unanswered", tags=["administration"])
    def admin_unanswered(_: str = Depends(require_admin)) -> list[dict]:
        return chat.unanswered()

    @app.get("/api/sources/stats", tags=["corpus"])
    def source_stats() -> list[dict]:
        return chat.citation_stats()

    @app.post("/api/eval/run", status_code=202, tags=["administration"])
    def eval_run(payload: EvalRequest = Body(default=EvalRequest()), _: str = Depends(require_admin)) -> dict:
        return {"run_id": evaluation.start(payload.mode, payload.sample, payload.top_k, background=background)}

    @app.get("/api/eval/results", tags=["administration"])
    def eval_results(_: str = Depends(require_admin)) -> dict:
        return {"runs": evaluation.runs(), "offline": evaluation.offline_results()}

    return app


def _default_app() -> FastAPI:
    return create_app()


app = _default_app()
