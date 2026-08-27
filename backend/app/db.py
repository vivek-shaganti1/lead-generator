"""SQLAlchemy engine/session wiring. Sync sessions keep FastAPI + Celery on one code path."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import anchor_sqlite_path, settings
from app.logging_config import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = anchor_sqlite_path(settings.database_url)
    if url.startswith("sqlite"):
        # In-memory SQLite needs a shared connection for tests to see the same data.
        connect_args = {"check_same_thread": False}
        if ":memory:" in url:
            return create_engine(
                url, connect_args=connect_args, poolclass=StaticPool, future=True
            )
        return create_engine(url, connect_args=connect_args, future=True)
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver specific
    if settings.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for workers and scripts."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables and ensure all model columns exist."""
    from sqlalchemy import inspect, text

    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)

    # SQLite column auto-sync for dev environment
    if settings.database_url.startswith("sqlite"):
        with engine.connect() as conn:
            insp = inspect(engine)
            for table_name, table in Base.metadata.tables.items():
                if table_name in insp.get_table_names():
                    existing_cols = {c["name"] for c in insp.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            try:
                                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"))
                                conn.commit()
                                log.info("db.column_added", table=table_name, column=col.name)
                            except Exception:
                                pass

    _stamp_alembic_head()


def _stamp_alembic_head() -> None:
    """Record that a create_all schema is already at head.

    Without this, a database built by create_all has the full schema but no
    revision, so the next `alembic upgrade head` replays the initial migration
    and dies on "table already exists". Best-effort: a missing alembic.ini is
    not a reason to fail startup.
    """
    if settings.env == "test":
        return
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini.is_file():
        return
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(ini.parent / "alembic"))
        cfg.set_main_option("sqlalchemy.url", anchor_sqlite_path(settings.database_url))
        command.stamp(cfg, "head")
        log.info("db.stamped_alembic_head")
    except Exception as exc:  # pragma: no cover - depends on local alembic state
        log.warning("db.stamp_failed", error=str(exc))
