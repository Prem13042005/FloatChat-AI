"""
src/api/main.py

FloatChat FastAPI AI Service.
Exposes the LangGraph orchestration engine and three primary AI agents through
a reliable, production-ready REST API for the Java backend and external clients.

Endpoints:
- POST /api/v1/chat  (and alias POST /api/v1/query): Query orchestration
- GET /health: Liveness probe
- GET /ready: Readiness probe checking database, postgis, and pgvector connectivity
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.agents.response.models import Citation, DataSummary, VisualizationSpec
from src.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    HealthResponse,
    ReadinessResponse,
    SQLMeta,
)
from src.config import Config, get_config
from src.database.connection import get_db_connection
from src.orchestration import FloatChatOrchestrator, FloatChatState

logger = logging.getLogger("floatchat.api")


# ===================================================================
# Lifespan Context & Dependency Injection
# ===================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Initializes shared FloatChatOrchestrator once on startup to avoid
    re-creating connections or agent instances per request.
    """
    config = getattr(app.state, "config", None) or get_config()
    logger.info(f"Initializing FloatChat FastAPI Service [Port: {config.api_port}]...")
    try:
        app.state.config = config
        if getattr(app.state, "orchestrator", None) is None:
            app.state.orchestrator = FloatChatOrchestrator(config=config)
        logger.info("FloatChat Orchestrator initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize FloatChat Orchestrator during startup: {e}")
        # Allow app to start so health/ready checks can report status
        app.state.config = config
        app.state.orchestrator = None

    yield

    logger.info("Shutting down FloatChat FastAPI Service...")


def create_app(config: Optional[Config] = None) -> FastAPI:
    """
    FastAPI Application Factory.
    Configures routes, middlewares, exception handlers, and CORS.
    """
    app_config = config or get_config()

    app = FastAPI(
        title="FloatChat AI Service",
        description="Conversational Ocean Data Discovery & Analysis Platform powered by LangGraph and ARGO data.",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.state.config = app_config

    # -------------------------------------------------------------------
    # CORS Middleware Configuration
    # -------------------------------------------------------------------
    allowed_origins = app_config.allowed_cors_origins
    if not allowed_origins:
        allowed_origins = ["http://localhost:3000", "http://localhost:8080"]

    logger.info(f"Configuring CORS with allowed origins: {allowed_origins}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------
    # Exception Handlers
    # -------------------------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Request validation error on {request.url.path}: {exc.errors()}")
        error_msgs = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            error_msgs.append(f"{loc}: {err.get('msg')}")
        message = "; ".join(error_msgs) if error_msgs else "Invalid request body."
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorDetail(
                error_code="VALIDATION_ERROR",
                message=message,
            ).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(f"HTTPException on {request.url.path} [{exc.status_code}]: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorDetail(
                error_code="HTTP_ERROR",
                message=str(exc.detail),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.url.path}: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorDetail(
                error_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while processing the request.",
            ).model_dump(),
        )

    # -------------------------------------------------------------------
    # Dependency: Get Orchestrator
    # -------------------------------------------------------------------
    def get_orchestrator(request: Request) -> FloatChatOrchestrator:
        orchestrator = getattr(request.app.state, "orchestrator", None)
        if orchestrator is None:
            # Fallback initialization if state wasn't populated
            config = getattr(request.app.state, "config", None) or get_config()
            orchestrator = FloatChatOrchestrator(config=config)
            request.app.state.orchestrator = orchestrator
        return orchestrator

    # -------------------------------------------------------------------
    # Endpoints
    # -------------------------------------------------------------------
    @app.get("/health", response_model=HealthResponse, tags=["Diagnostics"])
    async def health_check():
        """
        Process liveness probe returning process status.
        """
        return HealthResponse(status="healthy", version="0.5.0")

    @app.get("/ready", response_model=ReadinessResponse, tags=["Diagnostics"])
    async def readiness_check(response: Response, request: Request):
        """
        Readiness probe checking PostgreSQL, PostGIS, pgvector, and LLM configuration
        without modifying any database state.
        """
        config = getattr(request.app.state, "config", None) or get_config()

        db_status = "unreachable"
        postgis_status = "unverified"
        pgvector_status = "unverified"
        details: Dict[str, Any] = {}
        is_ready = True

        # Check PostgreSQL + PostGIS + pgvector connectivity read-only
        try:
            conn = get_db_connection(config)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('postgis', 'vector');")
                extensions = {row[0] for row in cur.fetchall()}
            conn.close()

            db_status = "connected"
            postgis_status = "available" if "postgis" in extensions else "missing"
            pgvector_status = "available" if "vector" in extensions else "missing"
        except Exception as e:
            is_ready = False
            db_status = "unreachable"
            # Sanitize error
            clean_err = str(e).split("\n")[0]
            details["database_error"] = clean_err
            logger.warning(f"Readiness database check failed: {clean_err}")

        # Check LLM / Embedding configuration
        llm_info = f"{config.llm_provider} ({config.ollama_model if config.llm_provider == 'ollama' else config.gemini_model})"
        emb_info = f"{config.embedding_provider} ({config.embedding_model})"

        readiness = ReadinessResponse(
            status="ready" if is_ready else "not_ready",
            database=db_status,
            postgis=postgis_status,
            pgvector=pgvector_status,
            llm_provider=llm_info,
            embedding_provider=emb_info,
            details=details,
        )

        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return readiness

    async def _execute_chat_workflow(
        payload: ChatRequest,
        orchestrator: FloatChatOrchestrator,
        timeout_seconds: float,
    ) -> ChatResponse:
        """Helper to invoke orchestrator with timeout and transform state to ChatResponse."""
        try:
            # Run blocking orchestrator.invoke in thread pool with timeout
            state: FloatChatState = await asyncio.wait_for(
                asyncio.to_thread(orchestrator.invoke, payload.query, payload.session_id),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Workflow timeout on query: '{payload.query[:60]}...' after {timeout_seconds}s")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Query execution timed out after {timeout_seconds} seconds.",
            )
        except Exception as e:
            logger.error(f"Orchestration execution error: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Workflow execution encountered an internal error.",
            )

        # Build SQLMeta if database query was executed
        sql_meta = None
        if state.get("generated_sql") or state.get("db_result"):
            db_res = state.get("db_result")
            sql_meta = SQLMeta(
                generated_sql=state.get("generated_sql"),
                execution_time_ms=state.get("db_execution_time_ms") or (db_res.execution_time_ms if db_res else None),
                row_count=state.get("db_row_count") or (db_res.row_count if db_res else 0),
                is_truncated=db_res.is_truncated if db_res else False,
            )

        # Parse citations
        raw_citations = state.get("citations") or []
        citations_list = []
        for c in raw_citations:
            if isinstance(c, dict):
                citations_list.append(Citation(**c))
            elif isinstance(c, Citation):
                citations_list.append(c)

        # Parse visualization_spec
        raw_viz = state.get("visualization_spec")
        viz_spec = None
        if raw_viz:
            if isinstance(raw_viz, dict):
                viz_spec = VisualizationSpec(**raw_viz)
            elif isinstance(raw_viz, VisualizationSpec):
                viz_spec = raw_viz

        # Parse data_summary
        raw_summary = state.get("data_summary")
        data_summary = None
        if raw_summary:
            if isinstance(raw_summary, dict):
                data_summary = DataSummary(**raw_summary)
            elif isinstance(raw_summary, DataSummary):
                data_summary = raw_summary

        return ChatResponse(
            session_id=state.get("session_id") or payload.session_id,
            intent_type=state.get("intent_type") or "UNKNOWN",
            answer=state.get("final_response") or "No response generated.",
            citations=citations_list,
            sql_meta=sql_meta,
            visualization_spec=viz_spec,
            data_summary=data_summary,
            status=state.get("status") or "SUCCESS",
            warnings=state.get("warnings") or [],
        )

    @app.post("/api/v1/chat", response_model=ChatResponse, tags=["Orchestration"])
    async def chat_endpoint(
        payload: ChatRequest,
        request: Request,
        orchestrator: FloatChatOrchestrator = Depends(get_orchestrator),
    ):
        """
        Primary conversational endpoint.
        Processes natural-language queries through the LangGraph multi-agent workflow.
        """
        config = getattr(request.app.state, "config", None) or get_config()
        return await _execute_chat_workflow(payload, orchestrator, config.request_timeout_seconds)

    @app.post("/api/v1/query", response_model=ChatResponse, tags=["Orchestration"], include_in_schema=False)
    async def query_endpoint_alias(
        payload: ChatRequest,
        request: Request,
        orchestrator: FloatChatOrchestrator = Depends(get_orchestrator),
    ):
        """Alias for /api/v1/chat conforming to API_CONTRACTS.md."""
        config = getattr(request.app.state, "config", None) or get_config()
        return await _execute_chat_workflow(payload, orchestrator, config.request_timeout_seconds)

    return app


app = create_app()
