"""Production database layer for the AI Platform Reliability Copilot.

Supports both:
  - SQLite  (local dev, zero-config, via aiosqlite)
  - PostgreSQL (production, via asyncpg / DATABASE_URL env var)

On startup, the database is seeded from CSV files if the tables are empty.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from backend.utils.config import DATA_DIR

logger = logging.getLogger(__name__)

# ── SQLite synchronous helpers (kept for tests & CSV seeding) ─────────────────
import sqlite3

DB_PATH = DATA_DIR / "platform_reliability.db"


def get_connection() -> sqlite3.Connection:
    """Return a synchronous SQLite connection (for CSV seeding / legacy tests)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def load_csv_to_sqlite(csv_path: Path, table_name: str) -> int:
    """Ingest a CSV file into an SQLite table.

    Returns the number of rows loaded, 0 if file missing, -1 on write error
    (e.g. read-only sandbox environment).
    """
    if not csv_path.exists():
        logger.warning("CSV not found, skipping: %s", csv_path)
        return 0
    df = pd.read_csv(csv_path)
    try:
        with get_connection() as conn:
            df.to_sql(table_name, conn, if_exists="replace", index=False)
            logger.info("Seeded table '%s' with %d rows from %s", table_name, len(df), csv_path.name)
    except sqlite3.OperationalError as exc:
        # Some sandboxed / read-only environments cannot write to the data dir.
        # CSV-backed analytics still work; this is non-fatal.
        logger.warning("Could not write SQLite table '%s': %s", table_name, exc)
        return -1
    return len(df)


def initialize_database() -> dict[str, int]:
    """Seed all three core telemetry tables from CSV files.

    Called once on application startup. Idempotent: uses ``if_exists='replace'``
    so re-running regenerates the tables from the latest CSVs.
    """
    results = {
        "logs": load_csv_to_sqlite(DATA_DIR / "synthetic_logs.csv", "logs"),
        "metrics": load_csv_to_sqlite(DATA_DIR / "service_metrics.csv", "metrics"),
        "incidents": load_csv_to_sqlite(DATA_DIR / "incidents.csv", "incidents"),
    }
    logger.info("Database initialization complete: %s", results)
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  Async SQLAlchemy engine (PostgreSQL / SQLite via aiosqlite)
# ─────────────────────────────────────────────────────────────────────────────

_async_engine = None
_async_session_factory = None


def _build_async_engine():
    """Build the async SQLAlchemy engine from DATABASE_URL.

    Lazy-imported so that projects without SQLAlchemy async extras don't fail
    at module load time.
    """
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from backend.utils.config import get_settings

        settings = get_settings()
        db_url = settings.database_url

        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}

        engine = create_async_engine(
            db_url,
            echo=settings.environment == "local",
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        logger.info("Async DB engine ready: %s", db_url.split("@")[-1])  # hide credentials
        return engine, session_factory
    except Exception as exc:
        logger.warning("Async engine unavailable (%s); falling back to sync SQLite.", exc)
        return None, None


def get_async_engine():
    """Return the singleton async engine, building it on first call."""
    global _async_engine, _async_session_factory
    if _async_engine is None:
        _async_engine, _async_session_factory = _build_async_engine()
    return _async_engine


def get_async_session_factory():
    """Return the async session factory."""
    global _async_session_factory
    if _async_session_factory is None:
        get_async_engine()
    return _async_session_factory


async def get_async_session():
    """FastAPI dependency that yields an async database session.

    Usage::

        @app.get("/example")
        async def example(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    factory = get_async_session_factory()
    if factory is None:
        raise RuntimeError("Async database session factory not available.")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all ORM-mapped tables (runs DDL if they don't exist).

    Called during application startup when async engine is available.
    """
    engine = get_async_engine()
    if engine is None:
        return
    try:
        from backend.database.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("All database tables created/verified.")
    except Exception as exc:
        logger.warning("Could not create tables via async engine: %s", exc)
