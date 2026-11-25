"""Local API for the Interview Copilot development vertical slice."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .application.generation import GenerationError, GenerationService
from .bootstrap import create_deepgram_provider, create_generation_service, create_whisper_provider
from .live import LiveRuntime, router as live_router
from .parsers import SUPPORTED_EXTENSIONS, parse_file
from .retrieval import assess_answer, suggest, build_session_report
from .semantic import SemanticIndex, SemanticInterrupted, SemanticUnavailable
from .semantic_indexing import SemanticIndexing
from .store import DuplicateDocumentError, KnowledgeStore

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=3000)


class SemanticIndexRequest(BaseModel):
    # Only a direct request may authorize downloading an embedding model.
    allow_download: bool = False
    document_id: str | None = Field(default=None, min_length=1, max_length=64)
    background: bool = False


class SessionRequest(BaseModel):
    mode: Literal["live", "practice"]


class EvaluateRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10_000)


def default_data_dir() -> Path:
    configured = os.environ.get("COPILOT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "InterviewCopilot"
    return Path.home() / ".local" / "share" / "interview-copilot"


def create_app(data_dir: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await asyncio.to_thread(application.state.indexing.start)
        try:
            yield
        finally:
            closing = asyncio.create_task(asyncio.to_thread(application.state.indexing.close))
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                # A cancelled lifespan must not abandon a native batch or its writer thread.
                await closing
                raise

    application = FastAPI(title="Interview Copilot API", version="0.1.2", lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    @application.middleware("http")
    async def reject_cross_origin_writes(request, call_next):
        # CORS alone does not prevent cross-origin form POST requests (CSRF).
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Origin not permitted"})
        return await call_next(request)

    store = KnowledgeStore(data_dir or default_data_dir())
    application.state.store = store
    application.state.semantic = SemanticIndex(store)
    application.state.indexing = SemanticIndexing(application.state.semantic,
        automatic_enabled=os.environ.get("COPILOT_AUTO_SEMANTIC_INDEX", "").strip().lower() in {"1", "true"},
        defer_for_live=lambda: application.state.live.connection_active)
    application.state.live = LiveRuntime(whisper=create_whisper_provider(), deepgram=create_deepgram_provider())
    try:
        application.state.generation = create_generation_service()
    except GenerationError:
        # Invalid optional configuration must not prevent capture/API startup.
        # No provider can run, but retain not_configured rather than reporting disabled.
        application.state.generation = GenerationService(enabled=True)
    application.include_router(live_router)

    @application.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.2"}

    @application.post("/documents", status_code=201)
    async def upload_document(file: UploadFile = File(...)):
        filename = Path((file.filename or "").replace("\\", "/")).name
        if not filename or Path(filename).suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Allowed: .pdf, .docx, .xlsx, .txt, .md")
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Maximum file size is 20 MB")
        try:
            entries = await asyncio.to_thread(parse_file, filename, payload)
            result = await asyncio.to_thread(store.import_document, filename, payload, entries)
        except DuplicateDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if application.state.indexing.automatic_enabled:
            try:
                await asyncio.to_thread(application.state.indexing.request, result["id"])
            except Exception:
                # Import is already committed. A scheduling failure must not masquerade as upload failure.
                result["semantic_indexing_error"] = "scheduling_failed"
        return result

    @application.get("/documents")
    def list_documents():
        return {"documents": store.list_documents()}

    @application.delete("/documents/{document_id}")
    def delete_document(document_id: str):
        if not store.delete_document(document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True}

    @application.post("/answers")
    def get_answer(request: AskRequest):
        return suggest(store, request.question)

    @application.get("/semantic/status")
    def semantic_status():
        return application.state.indexing.status()

    @application.post("/semantic/index")
    def semantic_index(request: SemanticIndexRequest):
        if request.document_id is not None and not store.semantic_documents(
                application.state.semantic.model_name, request.document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        if request.background and request.allow_download:
            raise HTTPException(status_code=422, detail="Las descargas requieren una solicitud manual separada.")
        try:
            if request.background:
                documents = store.semantic_documents(application.state.semantic.model_name, request.document_id)
                for document in documents:
                    application.state.indexing.request(document["document_id"])
                return application.state.indexing.status()
            return application.state.semantic.index(allow_download=request.allow_download,
                                                    document_id=request.document_id)
        except SemanticUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SemanticInterrupted as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="No se pudo completar la indexación semántica. Puedes volver a intentarlo.") from exc

    @application.post("/sessions", status_code=201)
    def create_session(request: SessionRequest):
        return store.create_session(request.mode)

    @application.get("/sessions/{session_id}")
    def get_session(session_id: str):
        result = store.get_session(session_id)
        if not result:
            raise HTTPException(status_code=404, detail="Session not found")
        return result

    @application.post("/sessions/{session_id}/next")
    def next_question(session_id: str):
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["mode"] != "practice":
            raise HTTPException(status_code=400, detail="Not a practice session")
        if session["finished_at"]:
            raise HTTPException(status_code=409, detail="Session already finished")
        if session["current_entry_id"]:
            raise HTTPException(status_code=409, detail="Answer the current question first")
        result = store.next_practice_question(session_id)
        if not result:
            raise HTTPException(status_code=404, detail="No unused Q&A questions available")
        return result

    @application.post("/sessions/{session_id}/finish")
    async def finish_session(session_id: str):
        transcription = application.state.live.transcriptions.get(session_id)
        if transcription is not None:
            await transcription.close()
        generation = application.state.live.generations.get(session_id)
        if generation is not None:
            await generation.close()
        try:
            finished = await asyncio.to_thread(store.finish_session, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not finished:
            raise HTTPException(status_code=404, detail="Session not found")
        session = await asyncio.to_thread(store.get_session, session_id)
        reviews = await asyncio.to_thread(store.session_reviews, session_id)
        return build_session_report(session, reviews)

    @application.get("/sessions/{session_id}/report")
    def session_report(session_id: str):
        session = store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return build_session_report(session, store.session_reviews(session_id))

    @application.post("/sessions/{session_id}/evaluate")
    def evaluate(session_id: str, request: EvaluateRequest):
        current = store.get_current_practice(session_id)
        if not current:
            raise HTTPException(status_code=409, detail="No active practice question")
        evaluation = assess_answer(request.answer, current["answer"])
        result = store.evaluate(session_id, request.answer, evaluation["score"])
        return {**evaluation, "expected_answer": result["answer"], "source": {"document_name": result["document_name"], "location": result["location"]}}

    return application


app = create_app()
