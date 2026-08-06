"""FastAPI entrypoint for MechResearch-Agent."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from config import Configuration, SearchAPI
from agent import DeepResearchAgent
from services.knowledge_base import KnowledgeBaseService
from services.evaluator import EvaluatorService
from services.pdf_export import build_pdf_bytes

logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)

logger.add(
    sink=sys.stderr,
    level="ERROR",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)


class ResearchRequest(BaseModel):
    """Payload for triggering a research run."""

    topic: str = Field(..., description="Research topic supplied by the user")
    search_api: SearchAPI | None = Field(
        default=None,
        description="Override the default search backend configured via env",
    )


class ResearchResponse(BaseModel):
    """HTTP response containing the generated report and structured tasks."""

    report_markdown: str = Field(
        ..., description="Markdown-formatted research report including sections"
    )
    todo_items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured TODO items with summaries and sources",
    )
    evaluation: dict[str, Any] | None = Field(
        default=None,
        description="Report quality evaluation result",
    )


class KBSearchRequest(BaseModel):
    query: str = Field(..., description="Search query for knowledge base")


class EvaluateRequest(BaseModel):
    report: str = Field(..., description="Report markdown to evaluate")


class PdfExportRequest(BaseModel):
    title: str = Field(..., description="Title used for the exported PDF file")
    report_markdown: str = Field(..., description="Markdown report content to export as PDF")


def _mask_secret(value: Optional[str], visible: int = 4) -> str:
    """Mask sensitive tokens while keeping leading and trailing characters."""
    if not value:
        return "unset"

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def _sanitize_filename(value: str, fallback: str = "MechResearch-Report") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value or "").strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[\x00-\x1f]+", "", cleaned)
    cleaned = cleaned[:80]
    return cleaned or fallback


def _build_config(payload: ResearchRequest) -> Configuration:
    overrides: Dict[str, Any] = {}

    if payload.search_api is not None:
        overrides["search_api"] = payload.search_api

    return Configuration.from_env(overrides=overrides)


_kb_service: KnowledgeBaseService | None = None


def _get_kb_service() -> KnowledgeBaseService:
    global _kb_service
    if _kb_service is None:
        config = Configuration.from_env()
        _kb_service = KnowledgeBaseService(config)
    return _kb_service


def create_app() -> FastAPI:
    app = FastAPI(title="MechResearch-Agent 工程技术深度研究智能体")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def log_startup_configuration() -> None:
        config = Configuration.from_env()

        if config.llm_provider == "ollama":
            base_url = config.sanitized_ollama_url()
        elif config.llm_provider == "lmstudio":
            base_url = config.lmstudio_base_url
        else:
            base_url = config.llm_base_url or "unset"

        search_api_val = config.search_api.value if isinstance(config.search_api, SearchAPI) else config.search_api
        logger.info(
            "MechResearch configuration loaded: provider={} model={} base_url={} search_api={} "
            "max_loops={} fetch_full_page={} tool_calling={} strip_thinking={} api_key={} "
            "enable_rag={} enable_evaluator={}",
            config.llm_provider,
            config.resolved_model() or "unset",
            base_url,
            search_api_val,
            config.max_web_research_loops,
            config.fetch_full_page,
            config.use_tool_calling,
            config.strip_thinking_tokens,
            _mask_secret(config.llm_api_key),
            config.enable_rag,
            config.enable_evaluator,
        )

    @app.get("/healthz")
    def health_check() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
            result = agent.run(payload.topic)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Research failed") from exc

        todo_payload = [
            {
                "id": item.id,
                "title": item.title,
                "intent": item.intent,
                "query": item.query,
                "status": item.status,
                "summary": item.summary,
                "sources_summary": item.sources_summary,
                "note_id": item.note_id,
                "note_path": item.note_path,
            }
            for item in result.todo_items
        ]

        evaluation_payload = None
        if result.evaluation:
            evaluation_payload = {
                "score": result.evaluation.score,
                "has_sources": result.evaluation.has_sources,
                "has_tech_stack": result.evaluation.has_tech_stack,
                "has_risks": result.evaluation.has_risks,
                "has_actionable_steps": result.evaluation.has_actionable_steps,
                "suggestions": result.evaluation.suggestions,
                "details": result.evaluation.details,
            }

        return ResearchResponse(
            report_markdown=(result.report_markdown or result.running_summary or ""),
            todo_items=todo_payload,
            evaluation=evaluation_payload,
        )

    @app.post("/research/stream")
    def stream_research(payload: ResearchRequest) -> StreamingResponse:
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def event_iterator() -> Iterator[str]:
            try:
                for event in agent.run_stream(payload.topic):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.exception("Streaming research failed")
                error_payload = {"type": "error", "detail": str(exc)}
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # ------------------------------------------------------------------
    # Knowledge Base endpoints
    # ------------------------------------------------------------------
    @app.post("/kb/upload")
    async def upload_to_kb(file: UploadFile = File(...)) -> dict[str, Any]:
        """Upload a document to the knowledge base."""
        kb = _get_kb_service()
        if not kb.available:
            raise HTTPException(
                status_code=503,
                detail="知识库未启用，请设置 ENABLE_RAG=true 并安装 qdrant-client",
            )

        suffix = Path(file.filename or "upload.tmp").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = kb.upload_document(tmp_path)
            return {"filename": file.filename, **result}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @app.get("/kb/stats")
    def kb_stats() -> dict[str, Any]:
        """Get knowledge base statistics."""
        kb = _get_kb_service()
        return kb.stats()

    @app.post("/kb/search")
    def kb_search(payload: KBSearchRequest) -> dict[str, Any]:
        """Search the knowledge base."""
        kb = _get_kb_service()
        if not kb.available:
            return {"status": "unavailable", "results": ""}
        result = kb.search(payload.query)
        return {"status": "ok", "results": result}

    # ------------------------------------------------------------------
    # Evaluation endpoint
    # ------------------------------------------------------------------
    @app.post("/evaluate")
    def evaluate_report(payload: EvaluateRequest) -> dict[str, Any]:
        """Evaluate a research report for quality."""
        config = Configuration.from_env()
        if not config.enable_evaluator:
            raise HTTPException(status_code=503, detail="评估功能未启用")

        from hello_agents import HelloAgentsLLM

        llm_kwargs: dict[str, Any] = {"temperature": 0.0}
        model_id = config.llm_model_id or config.local_llm
        if model_id:
            llm_kwargs["model"] = model_id
        provider = (config.llm_provider or "").strip()
        if provider:
            llm_kwargs["provider"] = provider
        if config.llm_base_url:
            llm_kwargs["base_url"] = config.llm_base_url
        if config.llm_api_key:
            llm_kwargs["api_key"] = config.llm_api_key

        llm = HelloAgentsLLM(**llm_kwargs)
        evaluator = EvaluatorService(llm)
        result = evaluator.evaluate(payload.report, [])

        return {
            "score": result.score,
            "has_sources": result.has_sources,
            "has_tech_stack": result.has_tech_stack,
            "has_risks": result.has_risks,
            "has_actionable_steps": result.has_actionable_steps,
            "suggestions": result.suggestions,
            "details": result.details,
        }

    @app.post("/export/pdf")
    def export_pdf(payload: PdfExportRequest) -> Response:
        report_markdown = payload.report_markdown.strip()
        if not report_markdown:
            raise HTTPException(status_code=400, detail="报告内容为空，无法导出 PDF")

        pdf_bytes = build_pdf_bytes(payload.title, report_markdown)
        safe_filename = _sanitize_filename(payload.title)
        ascii_filename = re.sub(r"[^\x20-\x7E]+", "_", safe_filename).strip(" _.-") or "MechResearch-Report"
        content_disposition = (
            f'attachment; filename="{ascii_filename}.pdf"; '
            f"filename*=UTF-8''{quote(safe_filename + '.pdf')}"
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": content_disposition},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8002,
        reload=True,
        log_level="info"
    )


