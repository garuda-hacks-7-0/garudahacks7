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
        "field_confidences": "JSON NOT NULL DEFAULT '{}'",
        "field_confidence_reasons": "JSON NOT NULL DEFAULT '{}'",
        "field_verification": "JSON NOT NULL DEFAULT '{}'",
        "evidence_assessments": "JSON NOT NULL DEFAULT '[]'",
        "follow_up_counts": "JSON NOT NULL DEFAULT '{}'",
        "incident_description": "TEXT NOT NULL DEFAULT ''",
        "evidence_urls": "JSON NOT NULL DEFAULT '[]'",
        "evidence_unavailable": "BOOLEAN NOT NULL DEFAULT 0",
        "ai_summary": "TEXT NOT NULL DEFAULT ''",
        "ai_confidence": "FLOAT NOT NULL DEFAULT 0",
        "triage_source": "VARCHAR(120) NOT NULL DEFAULT 'heuristic'",
        "review_required": "BOOLEAN NOT NULL DEFAULT 0",
        "severity_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
        "medical_status_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
        "reporter_is_farmer": "BOOLEAN",
        "reporter_is_local": "BOOLEAN",
        "follow_up_available": "BOOLEAN",
        "readiness_score": "INTEGER NOT NULL DEFAULT 0",
        "readiness_critique": "JSON NOT NULL DEFAULT '[]'",
        "farmer_profile_id": "INTEGER",
        "location_shared": "BOOLEAN NOT NULL DEFAULT 0",
        "location_verification_status": "VARCHAR(30) NOT NULL DEFAULT 'missing'",
        "village": "VARCHAR(160) NOT NULL DEFAULT ''",
        "district": "VARCHAR(160) NOT NULL DEFAULT ''",
        "regency": "VARCHAR(160) NOT NULL DEFAULT ''",
        "response_status": "VARCHAR(30) NOT NULL DEFAULT 'new'",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.exec_driver_sql(
                    f"ALTER TABLE reports ADD COLUMN {name} {definition}"
                )

        connection.exec_driver_sql(
            "UPDATE reports SET location_verification_status = CASE "
            "WHEN location_shared = 1 AND lat IS NOT NULL AND lon IS NOT NULL "
            "THEN 'verified_shared' "
            "WHEN lat IS NOT NULL AND lon IS NOT NULL THEN 'verified_geocoded' "
            "WHEN village <> '' AND district <> '' AND regency <> '' "
            "THEN 'needs_verification' ELSE 'missing' END "
            "WHERE location_verification_status = 'missing'"
        )

        table_additions = {
            "farmer_profiles": {
                "privacy_consent_at": "DATETIME",
                "privacy_consent_version": "VARCHAR(40)",
                "privacy_consent_method": "VARCHAR(40)",
            },
            "inbound_messages": {
                "button_payload": "VARCHAR(128)",
            },
        }
        table_names = set(inspector.get_table_names())
        for table_name, columns in table_additions.items():
            if table_name not in table_names:
                continue
            table_existing = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for name, definition in columns.items():
                if name not in table_existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"
                    )
