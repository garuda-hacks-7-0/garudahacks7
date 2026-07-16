from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dashboard import region_detail, update_report_status
from app.config import Settings
from app.db import Base
from app.models import Organization, OutboundMessage, Region, Report
from app.schemas import ReportStatusUpdateIn
from app.services.classifier import MockClassifier, OpenRouterClassifier
from app.services.geocoder import GeoResult, MockGeocoder
from app.services.triage import CONSENT_NOTICE, TriageService


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


class StubGeocoder(MockGeocoder):
    def resolve(self, text, lat=None, lon=None, label=None):
        if lat is not None and lon is not None:
            return GeoResult(lat, lon, label or "Shared location", label or "Shared")
        if "sayung" in text.lower():
            return self.places["sayung"]
        return None


def test_stateful_intake_ack_consent_and_sequential_followups(db):
    service = TriageService(classifier=MockClassifier(), geocoder=StubGeocoder())

    report, reply = service.ingest(db, sender="farmer-1", text="banjir")
    assert f"TT-{report.id:04d}" in reply
    assert CONSENT_NOTICE in reply
    assert "Lokasinya" in reply

    report, reply = service.ingest(db, sender="farmer-1", text="Sayung")
    assert "Seberapa parah" in reply

    report, reply = service.ingest(db, sender="farmer-1", text="parah")
    assert "kebutuhan medis" in reply

    report, reply = service.ingest(db, sender="farmer-1", text="tidak")
    assert report.status == "complete"
    assert report.severity == "high"
    assert report.medical_needed is False
    assert "sudah lengkap" in reply


def test_openrouter_classifier_uses_strict_schema_and_model_fallbacks():
    captured = {}
    payload = {
        "category": "flood",
        "severity": "critical",
        "medical_needed": True,
        "missing_fields": [],
        "needs": ["evakuasi"],
        "summary": "Banjir memutus akses dan membutuhkan evakuasi.",
        "confidence": 0.94,
    }

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model="openai/gpt-5-mini",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=__import__("json").dumps(payload))
                    )
                ],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    settings = Settings(
        openrouter_api_key="test-key",
        openrouter_model="openai/gpt-5-mini",
        openrouter_fallback_models="google/gemini-2.5-flash",
    )
    result = OpenRouterClassifier(settings=settings, client=client).classify(
        "banjir dan jalan putus", "https://example.com/flood.jpg"
    )

    assert result.category == "flood"
    assert result.source == "openrouter:openai/gpt-5-mini"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["extra_body"]["models"] == ["google/gemini-2.5-flash"]
    assert captured["extra_body"]["provider"]["data_collection"] == "deny"
    assert captured["messages"][1]["content"][1]["type"] == "image_url"


def _make_region_report(db):
    region = Region(
        name="Sayung",
        lat=-6.9218,
        lon=110.5157,
        weather_risk=0.8,
        report_risk=0.9,
        risk_score=0.85,
        last_summary="Satu laporan banjir.",
    )
    report = Report(
        sender="whatsapp:+628123",
        text="banjir parah",
        image_url="https://example.com/private.jpg",
        category="flood",
        severity="high",
        medical_needed=False,
        needs=["pompa"],
        ai_summary="Sawah terdampak banjir.",
        ai_confidence=0.9,
        triage_source="heuristic",
        status="complete",
        response_status="new",
        lat=-6.9201,
        lon=110.5199,
        location_label="RT 01 Sayung",
        region=region,
    )
    db.add_all([region, report])
    db.commit()
    db.refresh(report)
    return region, report


def test_public_region_payload_has_no_reporter_photo_or_precise_pin(db):
    region, _ = _make_region_report(db)
    public = region_detail(region.id, view="public", db=db).model_dump()

    serialized = str(public)
    assert "reports" not in public
    assert "whatsapp:" not in serialized
    assert "private.jpg" not in serialized
    assert "RT 01" not in serialized
    assert public["lat"] == round(region.lat, 2)
    assert public["lon"] == round(region.lon, 2)

    responder = region_detail(region.id, view="responder", db=db).model_dump()
    assert responder["reports"][0]["reporter_alias"].startswith("Petani TT-")
    assert "sender" not in responder["reports"][0]
    assert responder["reports"][0]["image_url"].endswith("private.jpg")


def test_status_update_names_verified_org_and_logs_notification(db):
    _, report = _make_region_report(db)
    organization = Organization(name="PMI Demak", type="volunteer", verified=True)
    db.add(organization)
    db.commit()
    db.refresh(organization)

    result = update_report_status(
        report.id,
        ReportStatusUpdateIn(
            status="verified",
            organization_id=organization.id,
            note="Tim menuju lokasi.",
        ),
        db,
    )

    assert result.organization_name == "PMI Demak"
    assert result.notification_status == "simulated"
    message = db.query(OutboundMessage).one()
    assert "diverifikasi oleh PMI Demak" in message.body
    assert message.recipient == "whatsapp:+628123"
