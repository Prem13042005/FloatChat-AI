"""
src/api/__init__.py

FloatChat FastAPI AI Service Package.
Exports application factory, request/response models, and main app instance.
"""

from src.api.main import app, create_app
from src.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    HealthResponse,
    ReadinessResponse,
    SQLMeta,
)

__all__ = [
    "app",
    "create_app",
    "ChatRequest",
    "ChatResponse",
    "HealthResponse",
    "ReadinessResponse",
    "SQLMeta",
    "ErrorDetail",
]
