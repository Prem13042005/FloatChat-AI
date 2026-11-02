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
import hmac
import logging
import time
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
    ScientificStatsResponse,
)
from src.config import Config, get_config
from src.database.connection import get_db_connection
from src.orchestration import FloatChatOrchestrator, FloatChatState
from src.orchestration.cancellation import CancellationToken, WorkflowCancelledError

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
        if getattr(app.state, "inference_gate_lock", None) is None:
            app.state.inference_gate_lock = asyncio.Lock()
        if getattr(app.state, "inference_semaphore", None) is None:
            app.state.inference_semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
        app.state.active_inferences = 0
        logger.info("FloatChat Orchestrator and Inference Concurrency Gate initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize FloatChat Orchestrator during startup: {e}")
        # Allow app to start so health/ready checks can report status
        app.state.config = config
        app.state.orchestrator = None
        if getattr(app.state, "inference_gate_lock", None) is None:
            app.state.inference_gate_lock = asyncio.Lock()
        if getattr(app.state, "inference_semaphore", None) is None:
            app.state.inference_semaphore = asyncio.Semaphore(config.max_concurrent_inferences)
        app.state.active_inferences = 0

    # Optional non-blocking startup warm-up for Ollama generation model
    if config.ollama_warmup_on_startup and config.llm_provider == "ollama":
        warmup_start = time.perf_counter()
        try:
            logger.info(
                "Executing startup warm-up for Ollama generation model: '%s' (keep_alive=%s, timeout=%0.1fs)...",
                config.ollama_model,
                config.ollama_keep_alive,
                config.ollama_warmup_timeout_seconds,
            )
            from src.llm import get_llm_provider
            warmup_provider = get_llm_provider(
                "ollama",
                model=config.ollama_model,
                base_url=config.ollama_base_url,
                timeout=config.ollama_warmup_timeout_seconds,
                keep_alive=config.ollama_keep_alive,
            )
            warmup_res = await asyncio.to_thread(
                warmup_provider.generate,
                prompt="ping",
                max_tokens=1,
                temperature=0.0,
            )
            warmup_dur_ms = round((time.perf_counter() - warmup_start) * 1000.0, 2)
            logger.info(
                "Ollama startup warm-up successful for '%s' in %.2fms (load=%.2fms)",
                config.ollama_model,
                warmup_dur_ms,
                warmup_res.load_duration_ms or 0.0,
            )
        except Exception as warmup_err:
            warmup_dur_ms = round((time.perf_counter() - warmup_start) * 1000.0, 2)
            logger.warning(
                "Ollama startup warm-up for '%s' skipped or failed after %.2fms (service will continue): %s",
                config.ollama_model,
                warmup_dur_ms,
                warmup_err,
            )

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
    app.state.inference_gate_lock = asyncio.Lock()
    app.state.inference_semaphore = asyncio.Semaphore(app_config.max_concurrent_inferences)
    app.state.active_inferences = 0

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
        error_code = "RATE_LIMIT_EXCEEDED" if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content=ErrorDetail(
                error_code=error_code,
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

    @app.get("/api/v1/stats", response_model=ScientificStatsResponse, tags=["Diagnostics"])
    async def get_scientific_stats(request: Request):
        """
        Retrieves verified dataset statistics directly from the ARGO PostgreSQL database
        via safe aggregate count queries using the dedicated read-only role.
        """
        config = getattr(request.app.state, "config", None) or get_config()
        _verify_internal_auth(request, config)

        try:
            conn = get_db_connection(config)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM argo_floats;")
                floats = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM argo_profiles;")
                profiles = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM argo_measurements;")
                measurements = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM argo_doc_embeddings;")
                chunks = cur.fetchone()[0]
                cur.execute("""
                    SELECT atttypmod
                    FROM pg_attribute
                    WHERE attrelid = 'argo_doc_embeddings'::regclass
                      AND attname = 'embedding';
                """)
                dim_row = cur.fetchone()
                dim = dim_row[0] if dim_row and dim_row[0] > 0 else config.expected_embedding_dimension
            conn.close()

            return ScientificStatsResponse(
                total_floats=floats,
                total_profiles=profiles,
                total_measurements=measurements,
                total_document_chunks=chunks,
                embedding_dimension=dim,
            )
        except Exception as e:
            logger.error(f"Failed to query scientific statistics: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to retrieve scientific statistics from database."
            )

    def _verify_internal_auth(request: Request, config: Config):
        """Validates the shared internal secret header if configured."""
        expected_secret = config.internal_secret
        if expected_secret:
            provided_secret = request.headers.get("X-Internal-Secret", "")
            if not provided_secret or not hmac.compare_digest(provided_secret, expected_secret):
                logger.warning(
                    "Unauthorized request to %s: Invalid or missing X-Internal-Secret header.",
                    request.url.path,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing internal service secret.",
                )

    async def _execute_chat_workflow(
        payload: ChatRequest,
        orchestrator: FloatChatOrchestrator,
        config: Config,
        request: Request,
    ) -> ChatResponse:
        """Helper to invoke orchestrator with authentication, concurrency gate, and worker lifecycle accounting."""
        req_start = time.perf_counter()
        _verify_internal_auth(request, config)

        if len(payload.query) > config.max_query_length:
            logger.warning(
                "Query length (%d characters) exceeds configured maximum limit of %d characters",
                len(payload.query),
                config.max_query_length,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Query length exceeds the maximum allowed limit of {config.max_query_length} characters.",
            )

        gate_lock: asyncio.Lock = getattr(request.app.state, "inference_gate_lock", None)
        if gate_lock is None:
            gate_lock = asyncio.Lock()
            request.app.state.inference_gate_lock = gate_lock

        # Atomic admission check & slot acquisition
        async with gate_lock:
            active = getattr(request.app.state, "active_inferences", 0)
            sem = getattr(request.app.state, "inference_semaphore", None)
            if active >= config.max_concurrent_inferences or (sem is not None and sem._value <= 0):
                logger.warning(
                    "AI inference concurrency limit reached (%d active >= %d max). Rejecting request with HTTP 429.",
                    active,
                    config.max_concurrent_inferences,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="AI service is currently busy processing another request. Please try again shortly.",
                    headers={"Retry-After": str(config.inference_retry_after_seconds)},
                )
            request.app.state.active_inferences = active + 1
            if sem is not None:
                sem._value = max(0, sem._value - 1)

        slot_acquired = True

        def _release_slot():
            nonlocal slot_acquired
            if slot_acquired:
                active_now = getattr(request.app.state, "active_inferences", 1)
                request.app.state.active_inferences = max(0, active_now - 1)
                sem = getattr(request.app.state, "inference_semaphore", None)
                if sem is not None:
                    sem._value = min(config.max_concurrent_inferences, sem._value + 1)
                slot_acquired = False
                logger.info(
                    "Inference worker completed. Active inferences remaining: %d",
                    request.app.state.active_inferences,
                )

        # Create one CancellationToken per request for cooperative cancellation
        cancellation_token = CancellationToken()

        def _invoke_worker():
            try:
                return orchestrator.invoke(
                    payload.query,
                    payload.session_id,
                    cancellation_token=cancellation_token,
                )
            except TypeError:
                # Fallback for test mocks or legacy signatures that only accept (query, session_id)
                return orchestrator.invoke(payload.query, payload.session_id)

        # Launch worker in background thread
        worker_task = asyncio.create_task(
            asyncio.to_thread(_invoke_worker)
        )

        # Safe completion callback: consumes exceptions and guarantees single slot release
        def _on_worker_done(fut: asyncio.Future):
            try:
                if not fut.cancelled():
                    exc = fut.exception()
                    if exc is not None:
                        if isinstance(exc, WorkflowCancelledError):
                            logger.info("Worker task exited cleanly following cooperative workflow cancellation.")
                        else:
                            logger.error(f"Unhandled exception in background worker task: {exc}", exc_info=exc)
            except Exception as cb_err:
                logger.warning(f"Error inspecting worker task completion: {cb_err}")
            finally:
                _release_slot()

        # Ensure slot is released only when the thread worker finishes, preventing CPU overload
        worker_task.add_done_callback(_on_worker_done)

        try:
            state: FloatChatState = await asyncio.wait_for(
                asyncio.shield(worker_task),
                timeout=config.request_timeout_seconds,
            )
        except asyncio.TimeoutError:
            cancellation_token.cancel()
            logger.warning(
                "Workflow timeout after %0.1fs for query length %d. Signalled cooperative cancellation to background worker.",
                config.request_timeout_seconds,
                len(payload.query),
            )
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Query execution timed out after {config.request_timeout_seconds} seconds.",
            )
        except asyncio.CancelledError:
            cancellation_token.cancel()
            logger.info("Request cancelled by client. Signalled cooperative cancellation to background worker.")
            raise
        except HTTPException:
            raise
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

        total_req_ms = round((time.perf_counter() - req_start) * 1000.0, 2)
        logger.info(
            "AI Chat request completed in %.2fms [session=%s, intent=%s, status=%s]",
            total_req_ms,
            payload.session_id or "anonymous",
            state.get("intent_type") or "UNKNOWN",
            state.get("status") or "SUCCESS",
        )

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
        return await _execute_chat_workflow(payload, orchestrator, config, request)

    @app.post("/api/v1/query", response_model=ChatResponse, tags=["Orchestration"], include_in_schema=False)
    async def query_endpoint_alias(
        payload: ChatRequest,
        request: Request,
        orchestrator: FloatChatOrchestrator = Depends(get_orchestrator),
    ):
        """Alias for /api/v1/chat conforming to API_CONTRACTS.md."""
        config = getattr(request.app.state, "config", None) or get_config()
        return await _execute_chat_workflow(payload, orchestrator, config, request)

    return app


app = create_app()
