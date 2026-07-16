from collections.abc import Generator

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_options: dict[str, object] = {"connect_args": connect_args}
if settings.database_url in {"sqlite://", "sqlite:///:memory:"}:
    engine_options["poolclass"] = StaticPool
engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_demo_sqlite_schema()


def _upgrade_demo_sqlite_schema() -> None:
    """Keep pre-PRD local demo databases usable without adding a migration framework."""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "reports" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("reports")}
    additions = {
        "needs": "JSON NOT NULL DEFAULT '[]'",
        "ai_summary": "TEXT NOT NULL DEFAULT ''",
        "ai_confidence": "FLOAT NOT NULL DEFAULT 0",
        "triage_source": "VARCHAR(120) NOT NULL DEFAULT 'heuristic'",
        "review_required": "BOOLEAN NOT NULL DEFAULT 0",
        "response_status": "VARCHAR(30) NOT NULL DEFAULT 'new'",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.exec_driver_sql(
                    f"ALTER TABLE reports ADD COLUMN {name} {definition}"
                )

