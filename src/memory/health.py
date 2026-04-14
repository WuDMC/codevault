"""Shared health check logic used by CLI, HTTP endpoints, and MCP tool."""

import importlib.metadata
import os
import sys


def check_health(config, db=None) -> dict:
    """Check system health. Returns dict with status, db, embeddings, version.

    Args:
        config: MemoryConfig with storage and embedding settings
        db: Optional database connection/object to test (if None, opens a new one)

    Returns:
        {"status": "ok"|"degraded", "db": "connected"|"error",
         "embeddings": "configured"|"not_configured"|"no_api_key",
         "version": "..."}
    """
    db_status = _check_db(config, db)
    embed_status = _check_embeddings(config)
    version = _get_version()
    status = "ok" if db_status == "connected" else "degraded"

    return {
        "status": status,
        "db": db_status,
        "embeddings": embed_status,
        "version": version,
    }


def _check_db(config, db=None) -> str:
    """Check database connectivity. Returns 'connected' or 'error'."""
    if db is not None:
        return _check_db_object(db)

    # No db object provided — open a fresh connection based on config
    if config.storage.backend == "postgresql":
        return _check_pg_from_config(config)
    else:
        # SQLite — always ok if config is loaded
        return "connected"


def _check_db_object(db) -> str:
    """Check an existing db object (SQLite conn or PG pool)."""
    try:
        # SQLite backend: has .conn attribute
        conn = getattr(db, "conn", None)
        if conn is not None:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            return "connected"

        # PG backend: has .pool attribute
        pool = getattr(db, "pool", None)
        if pool is not None:
            pg_conn = pool.getconn()
            try:
                cur = pg_conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            finally:
                pool.putconn(pg_conn)
            return "connected"

        return "error"
    except Exception as e:
        print(f"[HEALTH] DB check failed: {e}", file=sys.stderr)
        return "error"


def _check_pg_from_config(config) -> str:
    """Open a fresh PG connection from config URL and test it."""
    conn = None
    try:
        import psycopg2
        conn = psycopg2.connect(config.storage.url)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        return "connected"
    except Exception as e:
        print(f"[HEALTH] DB check failed: {e}", file=sys.stderr)
        return "error"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _check_embeddings(config) -> str:
    """Check embedding provider configuration."""
    try:
        provider = config.embedding.provider
        if not provider:
            return "not_configured"
        if provider == "openai":
            api_key = config.embedding.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return "no_api_key"
        return "configured"
    except Exception:
        return "not_configured"


def _get_version() -> str:
    """Get package version from metadata."""
    try:
        return importlib.metadata.version("codevault")
    except Exception:
        return "unknown"
