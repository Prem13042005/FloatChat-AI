"""
src/database/connection.py

FloatChat Database Connection Management.
Provides managed connections to PostgreSQL using application configuration.
Sanitizes connection errors to ensure credentials are never leaked.
"""

from typing import Optional
import psycopg2
from src.config import Config, get_config
from src.database.exceptions import DatabaseConnectionError


def get_db_connection(config: Optional[Config] = None) -> psycopg2.extensions.connection:
    """
    Establishes a connection to the PostgreSQL database using application configuration.

    Args:
        config: Optional Config instance. Defaults to get_config().

    Returns:
        An open psycopg2 connection.

    Raises:
        DatabaseConnectionError: If connection cannot be established.
    """
    cfg = config or get_config()
    try:
        conn = psycopg2.connect(
            host=cfg.postgres_host,
            port=cfg.postgres_port,
            dbname=cfg.postgres_db,
            user=cfg.postgres_user,
            password=cfg.postgres_password,
            connect_timeout=5,
        )
        return conn
    except Exception as e:
        # Sanitize exception message: NEVER expose password or connection URI
        error_name = type(e).__name__
        sanitized_msg = (
            f"Failed to connect to PostgreSQL database '{cfg.postgres_db}' "
            f"on {cfg.postgres_host}:{cfg.postgres_port}: {error_name}"
        )
        raise DatabaseConnectionError(sanitized_msg) from None
