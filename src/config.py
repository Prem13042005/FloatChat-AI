"""
src/config.py

FloatChat Centralized Configuration System.
Environment-driven configuration with sensible defaults matching .env.example.
"""

import os
from dataclasses import dataclass
from typing import Optional


def _load_env_file():
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v


_load_env_file()


@dataclass
class Config:
    # -------------------------------------------------------------------
    # LLM Provider Configuration
    # -------------------------------------------------------------------
    llm_provider: str = ""
    ollama_base_url: str = ""
    ollama_model: str = ""
    ollama_timeout_seconds: float = 30.0
    ollama_keep_alive: str = "30m"
    ollama_warmup_on_startup: bool = True
    ollama_warmup_timeout_seconds: float = 5.0
    ollama_num_predict_query_understanding: int = 300
    ollama_num_predict_data_query: int = 384
    ollama_num_predict_response: int = 512

    gemini_api_key: Optional[str] = None
    gemini_model: str = ""
    gemini_timeout_seconds: float = 30.0

    # -------------------------------------------------------------------
    # PostgreSQL + PostGIS Database Configuration
    # -------------------------------------------------------------------
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_readonly_user: str = ""
    postgres_readonly_password: str = ""
    postgres_statement_timeout_ms: int = 5000

    # -------------------------------------------------------------------
    # Vector Search & RAG Configuration (pgvector)
    # -------------------------------------------------------------------
    embedding_provider: str = ""
    embedding_model: str = ""
    vector_top_k: int = 4
    vector_similarity_threshold: float = 0.70
    expected_embedding_dimension: int = 768
    ollama_embedding_keep_alive: str = "5m"

    # -------------------------------------------------------------------
    # FastAPI Server Configuration
    # -------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = ""
    request_timeout_seconds: float = 60.0
    max_query_length: int = 2000
    max_concurrent_inferences: int = 1
    inference_retry_after_seconds: int = 30
    internal_secret: str = ""

    def __post_init__(self):
        if not self.llm_provider:
            self.llm_provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        if not self.ollama_base_url:
            self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        if not self.ollama_model:
            self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b-instruct")
        if self.ollama_timeout_seconds == 30.0:
            self.ollama_timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30.0"))
        if self.ollama_keep_alive == "30m":
            self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        if self.ollama_warmup_on_startup:
            warmup_env = os.getenv("OLLAMA_WARMUP_ON_STARTUP", "true").strip().lower()
            self.ollama_warmup_on_startup = warmup_env in ("true", "1", "yes", "on")
        if self.ollama_warmup_timeout_seconds == 5.0:
            self.ollama_warmup_timeout_seconds = float(os.getenv("OLLAMA_WARMUP_TIMEOUT_SECONDS", "5.0"))
        if self.ollama_embedding_keep_alive == "5m":
            self.ollama_embedding_keep_alive = os.getenv("OLLAMA_EMBEDDING_KEEP_ALIVE", "5m")

        def _parse_and_validate_int(env_name: str, current_val: int, default_val: int) -> int:
            val_to_check = current_val
            if current_val == default_val and env_name in os.environ:
                raw = os.environ[env_name]
                try:
                    val_to_check = int(raw)
                except (ValueError, TypeError):
                    raise ValueError(f"{env_name} must be a positive integer, got {raw!r}")
            elif not isinstance(val_to_check, int) or isinstance(val_to_check, bool):
                try:
                    val_to_check = int(val_to_check)
                except (ValueError, TypeError):
                    raise ValueError(f"{env_name} must be a positive integer, got {val_to_check!r}")

            if val_to_check <= 0:
                raise ValueError(f"{env_name} must be a positive integer, got {val_to_check}")
            return val_to_check

        self.ollama_num_predict_query_understanding = _parse_and_validate_int(
            "OLLAMA_NUM_PREDICT_QUERY_UNDERSTANDING",
            self.ollama_num_predict_query_understanding,
            300,
        )
        self.ollama_num_predict_data_query = _parse_and_validate_int(
            "OLLAMA_NUM_PREDICT_DATA_QUERY",
            self.ollama_num_predict_data_query,
            384,
        )
        self.ollama_num_predict_response = _parse_and_validate_int(
            "OLLAMA_NUM_PREDICT_RESPONSE",
            self.ollama_num_predict_response,
            512,
        )

        if self.gemini_api_key is None:
            self.gemini_api_key = os.getenv("GEMINI_API_KEY", None)
        if not self.gemini_model:
            self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        if self.gemini_timeout_seconds == 30.0:
            self.gemini_timeout_seconds = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30.0"))

        if not self.postgres_host:
            self.postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        if self.postgres_port == 5432:
            self.postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
        if not self.postgres_db:
            self.postgres_db = os.getenv("POSTGRES_DB", "floatchat_db")

        # Preferred read-only credentials for AI query engine
        if not self.postgres_readonly_user:
            self.postgres_readonly_user = os.getenv("POSTGRES_READONLY_USER", "")
        if not self.postgres_readonly_password:
            self.postgres_readonly_password = os.getenv("POSTGRES_READONLY_PASSWORD", "")

        if not self.postgres_user:
            self.postgres_user = self.postgres_readonly_user or os.getenv("POSTGRES_USER", "floatchat_user")
        if not self.postgres_password:
            self.postgres_password = self.postgres_readonly_password or os.getenv("POSTGRES_PASSWORD", "floatchat_password")

        if self.postgres_statement_timeout_ms == 5000:
            self.postgres_statement_timeout_ms = int(os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS", "5000"))

        if not self.embedding_provider:
            self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
        if self.embedding_provider == "local":
            self.embedding_provider = "ollama"
        if not self.embedding_model:
            self.embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
        if self.vector_top_k == 4:
            self.vector_top_k = int(os.getenv("VECTOR_TOP_K", "4"))
        if self.vector_similarity_threshold == 0.70:
            self.vector_similarity_threshold = float(os.getenv("VECTOR_SIMILARITY_THRESHOLD", "0.70"))
        if self.expected_embedding_dimension == 768:
            self.expected_embedding_dimension = int(os.getenv("EXPECTED_EMBEDDING_DIMENSION", "768"))

        if self.api_host == "127.0.0.1":
            self.api_host = os.getenv("FASTAPI_HOST") or os.getenv("API_HOST", "127.0.0.1")
        if self.api_port == 8000:
            port_val = os.getenv("FASTAPI_PORT") or os.getenv("API_PORT", "8000")
            self.api_port = int(port_val)
        if not self.cors_origins:
            self.cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080")
        if self.request_timeout_seconds == 60.0:
            self.request_timeout_seconds = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60.0"))
        if self.max_query_length == 2000:
            self.max_query_length = int(os.getenv("MAX_QUERY_LENGTH", "2000"))
        if self.max_concurrent_inferences == 1:
            self.max_concurrent_inferences = int(os.getenv("MAX_CONCURRENT_INFERENCES", "1"))
        if self.inference_retry_after_seconds == 30:
            self.inference_retry_after_seconds = int(os.getenv("INFERENCE_RETRY_AFTER_SECONDS", "30"))
        if not self.internal_secret:
            self.internal_secret = os.getenv("FLOATCHAT_INTERNAL_SECRET", "")

    @property
    def allowed_cors_origins(self) -> list:
        """Parses comma-separated cors_origins string into a list of origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]



def get_config() -> Config:
    """Returns a fresh Config instance reading current environment variables."""
    return Config()
