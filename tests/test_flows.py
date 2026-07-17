from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dashboard as dashboard_api, webhooks
from app.api.dashboard import create_alert, region_detail, update_report_status
from app.config import Settings
from app.db import Base
from app.models import (
    ConversationState,
    FarmerProfile,
    InboundMessage,
    LocalContact,
    Organization,
    OutboundMessage,
    Region,
    Report,
)
from app.schemas import AlertCreateIn, ReportStatusUpdateIn
from app.services.classifier import MockClassifier, OpenRouterClassifier
from app.services.geocoder import GeoResult, MockGeocoder
from app.services.notifications import NotificationService, WhatsAppNotifier
from app.services.triage import (
    CONSENT_NOTICE,
    EVIDENCE_TARGET,
    PRIVACY_CONSENT_ACCEPTED,
    PRIVACY_CONSENT_DECLINED,
    PRIVACY_CONSENT_PROMPT,
    PRIVACY_CONSENT_VERSION,
    TriageService,
)


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


class ManualFailingGeocoder(MockGeocoder):
    def resolve(self, text, lat=None, lon=None, label=None):
        if lat is not None and lon is not None:
            return GeoResult(
                lat,
                lon,
                label or "Shared location",
                label or "Shared location",
            )
        return None


class CountingClassifier(MockClassifier):
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def classify(self, text, image_url=None):
        self.calls.append((text, image_url))
        return super().classify(text, image_url)


def test_consent_gate_blocks_storage_and_ai_until_button_accepts(db):
    classifier = CountingClassifier()
    service = TriageService(classifier=classifier, geocoder=StubGeocoder())

    report, reply = service.ingest(
        db,
        sender="whatsapp:+628100",
        text="Hi",
        image_url="https://example.com/not-yet-consented.jpg",
    )

    assert report is None
    assert reply == PRIVACY_CONSENT_PROMPT
    assert classifier.calls == []
    assert db.query(FarmerProfile).count() == 0
    assert db.query(InboundMessage).count() == 0
    assert db.query(Report).count() == 0

    report, reply = service.ingest(
        db,
        sender="whatsapp:+628100",
        text="SETUJU",
        button_payload="CONSENT_ACCEPT",
    )

    assert report is None
    assert reply == PRIVACY_CONSENT_ACCEPTED
    assert classifier.calls == []
    profile = db.query(FarmerProfile).one()
    assert profile.privacy_consent_at is not None
    assert profile.privacy_consent_version == PRIVACY_CONSENT_VERSION
    assert profile.privacy_consent_method == "whatsapp_button"
    accepted_message = db.query(InboundMessage).one()
    assert accepted_message.button_payload == "CONSENT_ACCEPT"

    report, _ = service.ingest(db, sender="whatsapp:+628100", text="LAPOR")

    assert report is not None
    assert len(classifier.calls) == 1
    assert db.query(InboundMessage).count() == 2


def test_consent_cancel_button_discards_message_without_storage_or_ai(db):
    classifier = CountingClassifier()
    service = TriageService(classifier=classifier, geocoder=StubGeocoder())

    report, reply = service.ingest(
        db,
        sender="whatsapp:+628101",
        text="BATAL",
        button_payload="CONSENT_CANCEL",
    )

    assert report is None
    assert reply == PRIVACY_CONSENT_DECLINED
    assert classifier.calls == []
    assert db.query(FarmerProfile).count() == 0
    assert db.query(InboundMessage).count() == 0
    assert db.query(Report).count() == 0


def test_consent_text_fallback_is_recorded(db):
    service = TriageService(classifier=CountingClassifier(), geocoder=StubGeocoder())

    _, reply = service.ingest(
        db,
        sender="whatsapp:+628102",
        text="saya setuju",
    )

    assert reply == PRIVACY_CONSENT_ACCEPTED
    profile = db.query(FarmerProfile).one()
    assert profile.privacy_consent_method == "whatsapp_text"


def test_every_inbound_message_is_forwarded_to_classifier(db):
    classifier = CountingClassifier()
    service = TriageService(
        classifier=classifier,
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )

    service.ingest(db, sender="farmer-ai-all", text="Hi")
    service.ingest(db, sender="farmer-ai-all", text="lapor")
    active_report, active_reply = service.ingest(
        db, sender="farmer-ai-all", text="Hi"
    )
    service.ingest(
        db,
        sender="farmer-ai-all",
        text="Banjir merendam sawah saya sejak pagi",
    )
    service.ingest(
        db,
        sender="farmer-ai-all",
        text="",
        image_url="https://example.com/evidence.jpg",
    )
    service.ingest(db, sender="farmer-ai-all", text="batal")

    assert len(classifier.calls) == 6
    assert classifier.calls[0][0] == "Hi"
    assert "[JAWABAN_TERBARU]\nHi" in classifier.calls[2][0]
    assert "[FIELD_AKTIF]\nevidence" in classifier.calls[3][0]
    assert classifier.calls[4][1] == "https://example.com/evidence.jpg"
    assert "[JAWABAN_TERBARU]\nbatal" in classifier.calls[5][0]
    assert active_report is not None
    assert "Halo 👋" in active_reply
    assert "Draft" in active_reply
    assert "Maaf, saya belum menangkap" not in active_reply


def test_greeting_is_friendly_and_does_not_create_a_report(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )

    report, reply = service.ingest(db, sender="farmer-greeting", text="Hi")

    assert report is None
    assert "terima kasih sudah menghubungi PetaNih! 🌾" in reply
    assert "1. Foto lokasi dan bukti terdampak" in reply
    assert "2. Lokasi terdampak — pilih salah satu" in reply
    assert "Share Location" in reply
    assert "bukan Live Location" in reply
    assert "Atau ketik Desa/Kelurahan, Kecamatan, dan Kota/Kabupaten" in reply
    assert "3. Deskripsi dampak lokasi" in reply
    assert "Confidence" not in reply
    assert db.query(Report).count() == 0
    assert db.query(ConversationState).count() == 0

    report, reply = service.ingest(db, sender="farmer-greeting", text="lapor")
    assert report is not None
    assert "mulai dibuat" in reply
    assert "Masih kurang:" in reply


def test_start_command_typo_and_repeated_command_do_not_pollute_report(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )

    report, reply = service.ingest(db, sender="farmer-command", text="LAPOT")
    assert report is not None
    assert "mulai dibuat" in reply

    same_report, reply = service.ingest(
        db, sender="farmer-command", text="LAPOR"
    )

    assert same_report.id == report.id
    assert same_report.text == "LAPOT"
    assert "Kita lanjutkan" in reply
    assert "Maaf, saya belum menangkap" not in reply


def test_whatsapp_webhook_acknowledges_immediately_and_queues_ai_work():
    tasks = BackgroundTasks()

    response = webhooks.whatsapp_webhook(
        tasks,
        from_number="whatsapp:+62000",
        body="LAPOR",
    )

    assert response.status_code == 200
    assert response.body.endswith(b"<Response/>")
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func is webhooks._process_whatsapp_message


def test_whatsapp_quick_reply_payload_maps_to_consent_action():
    tasks = BackgroundTasks()

    webhooks.whatsapp_webhook(
        tasks,
        from_number="whatsapp:+62000",
        body="SETUJU",
        button_text="SETUJU",
        button_payload="CONSENT_ACCEPT",
    )

    assert tasks.tasks[0].args[1] == "SETUJU"
    assert tasks.tasks[0].args[-1] == "CONSENT_ACCEPT"


def test_background_whatsapp_work_sends_reply_via_notifier(monkeypatch):
    sent = []

    class FakeDb:
        def get(self, model, object_id):
            return SimpleNamespace(id=object_id)

        def rollback(self):
            pass

        def close(self):
            pass

    class FakeTriage:
        def ingest(self, db, **kwargs):
            return SimpleNamespace(id=42), "Balasan setelah AI selesai."

    class FakeNotifications:
        def send(self, db, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(webhooks, "SessionLocal", FakeDb)
    monkeypatch.setattr(webhooks, "triage", FakeTriage())
    monkeypatch.setattr(webhooks, "notifications", FakeNotifications())

    webhooks._process_whatsapp_message(
        "whatsapp:+62000", "LAPOR", [], None, None, None
    )

    assert sent == [
        {
            "recipient": "whatsapp:+62000",
            "body": "Balasan setelah AI selesai.",
            "kind": "intake_reply",
            "report_id": 42,
            "content_sid": None,
            "persist": True,
        }
    ]


def test_background_consent_prompt_uses_quick_reply_without_persisting(monkeypatch):
    sent = []

    class FakeDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class FakeTriage:
        def ingest(self, db, **kwargs):
            return None, PRIVACY_CONSENT_PROMPT

    class FakeNotifications:
        def send(self, db, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(webhooks, "SessionLocal", FakeDb)
    monkeypatch.setattr(webhooks, "triage", FakeTriage())
    monkeypatch.setattr(webhooks, "notifications", FakeNotifications())
    monkeypatch.setattr(
        webhooks,
        "settings",
        SimpleNamespace(twilio_consent_content_sid="HX-consent"),
    )

    webhooks._process_whatsapp_message(
        "whatsapp:+62001", "Hi", [], None, None, None
    )

    assert sent == [
        {
            "recipient": "whatsapp:+62001",
            "body": PRIVACY_CONSENT_PROMPT,
            "kind": "privacy_consent",
            "report_id": None,
            "content_sid": "HX-consent",
            "persist": False,
        }
    ]


def test_twilio_notifier_sends_quick_reply_content_without_body():
    created = []

    class Messages:
        def create(self, **kwargs):
            created.append(kwargs)
            return SimpleNamespace(sid="SM123")

    client = SimpleNamespace(messages=Messages())
    notifier = WhatsAppNotifier(
        settings=Settings(
            twilio_account_sid="AC123",
            twilio_auth_token="secret",
            twilio_whatsapp_from="whatsapp:+14155238886",
        ),
        client=client,
    )

    result = notifier.send(
        "whatsapp:+628123",
        PRIVACY_CONSENT_PROMPT,
        content_sid="HX123",
    )

    assert result.status == "sent"
    assert created == [
        {
            "from_": "whatsapp:+14155238886",
            "to": "whatsapp:+628123",
            "content_sid": "HX123",
        }
    ]


def test_unpersisted_notification_is_not_written_to_database(db):
    notifier = WhatsAppNotifier(settings=Settings())
    service = NotificationService(notifier=notifier)

    result = service.send(
        db,
        recipient="whatsapp:+628199",
        body=PRIVACY_CONSENT_PROMPT,
        kind="privacy_consent",
        persist=False,
    )

    assert result.delivery_status == "simulated"
    assert db.query(OutboundMessage).count() == 0


def test_stale_greeting_draft_is_cleaned_up_after_upgrade(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    stale = Report(
        sender="farmer-stale",
        text="Hi",
        incident_description="",
        category="unknown",
        status="needs_follow_up",
    )
    db.add(stale)
    db.commit()
    db.refresh(stale)
    db.add(
        ConversationState(
            sender="farmer-stale",
            report_id=stale.id,
            pending_fields="location,severity,medical_needed",
        )
    )
    db.commit()

    report, reply = service.ingest(db, sender="farmer-stale", text="Hi")

    assert report is None
    assert "terima kasih sudah menghubungi PetaNih! 🌾" in reply
    assert db.query(Report).count() == 0
    assert db.query(ConversationState).count() == 0


def test_stateful_intake_ack_consent_and_sequential_followups(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )

    report, reply = service.ingest(db, sender="farmer-1", text="LAPOR")
    assert f"TT-{report.id:04d}" in reply
    assert CONSENT_NOTICE in reply
    assert report.readiness_score == 0
    assert "upload foto lokasi" in reply
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")

    report, reply = service.ingest(
        db, sender="farmer-1", text="", image_url="https://example.com/bukti.jpg"
    )
    assert report.readiness_score == 25
    assert "Desa/Kelurahan" in reply
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")

    report, reply = service.ingest(db, sender="farmer-1", text="Sayung")
    assert report.village == "Sayung"
    assert "Kecamatan" in reply

    report, reply = service.ingest(db, sender="farmer-1", text="Sayung")
    assert report.district == "Sayung"
    assert "Kota/Kabupaten" in reply

    report, reply = service.ingest(db, sender="farmer-1", text="Demak")
    assert report.regency == "Demak"
    assert "Ceritakan dampak" in reply
    assert report.readiness_score == 69

    report, reply = service.ingest(db, sender="farmer-1", text="Banjir merendam dua hektare sawah dan merusak tanaman padi sejak pagi")
    assert report.status == "needs_follow_up"
    assert report.readiness_score == 69
    assert "petani atau penggarap" in reply
    assert "Balas YA atau TIDAK" in reply
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")

    report, reply = service.ingest(db, sender="farmer-1", text="ya")
    assert report.status == "complete"
    assert report.readiness_score == 100
    assert report.location_label == "Sayung, Sayung, Demak"
    assert len(report.evidence_urls) == EVIDENCE_TARGET
    assert "siap ditindaklanjuti" in reply
    assert db.query(ConversationState).count() == 0
    assert db.query(FarmerProfile).count() == 1
    assert report.reporter_is_local is True
    assert db.query(InboundMessage).count() == 7


def test_structured_message_shows_only_remaining_gap_and_reaches_ready(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    message = (
        "Desa/Kelurahan: Sayung\n"
        "Kecamatan: Sayung\n"
        "Kabupaten: Demak\n"
        "Deskripsi: Banjir merendam dua hektare sawah sejak pagi dan merusak padi.\n"
        "Status petani: ya\n"
        "Petani setempat: ya\n"
        "Bisa dihubungi: ya"
    )

    report, reply = service.ingest(db, sender="farmer-structured", text=message)

    assert report.readiness_score == 69
    assert report.readiness_critique == ["foto bukti terdampak belum diunggah"]
    assert "upload foto lokasi" in reply
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")

    report, reply = service.ingest(
        db,
        sender="farmer-structured",
        text="",
        image_url="https://example.com/1.jpg",
    )

    assert report.readiness_score == 100
    assert report.readiness_critique == []
    assert report.status == "complete"
    assert len(report.evidence_urls) == EVIDENCE_TARGET
    assert "siap ditindaklanjuti" in reply


def test_static_shared_location_replaces_manual_admin_location_fields(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )

    report, reply = service.ingest(
        db,
        sender="farmer-share-location",
        text=(
            "Deskripsi: Banjir merendam sawah dan merusak tanaman padi sejak pagi.\n"
            "Petani setempat: ya"
        ),
        image_url="https://example.com/evidence.jpg",
        lat=-6.9218,
        lon=110.5157,
        location_label="Lokasi sawah terdampak",
    )

    assert report.location_shared is True
    assert report.lat == -6.9218
    assert report.lon == 110.5157
    assert report.location_label == "Lokasi sawah terdampak"
    assert report.village == ""
    assert report.district == ""
    assert report.regency == ""
    assert report.readiness_score == 100
    assert report.status == "complete"
    assert "Desa/Kelurahan" not in reply
    assert "siap ditindaklanjuti" in reply


def test_unresolved_manual_location_lowers_readiness_and_requests_verification(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=ManualFailingGeocoder(),
        privacy_consent_required=False,
    )
    message = (
        "Desa: Desasalah\n"
        "Kecamatan: Kecamatansalah\n"
        "Kabupaten: Kabupatensalah\n"
        "Deskripsi: Banjir merendam sawah dan merusak tanaman padi sejak pagi.\n"
        "Petani setempat: ya"
    )

    report, reply = service.ingest(
        db,
        sender="farmer-bad-manual-location",
        text=message,
        image_url="https://example.com/evidence.jpg",
    )

    assert report.location_verification_status == "needs_verification"
    assert report.lat is None
    assert report.lon is None
    assert report.readiness_score == 69
    assert report.review_required is True
    assert "lokasi manual belum berhasil diverifikasi di peta" in reply
    assert "patokan terdekat" in reply
    assert "Share Location WhatsApp" in reply

    report, reply = service.ingest(
        db,
        sender="farmer-bad-manual-location",
        text="",
        lat=-6.9218,
        lon=110.5157,
        location_label="Sawah dekat balai desa",
    )

    assert report.location_verification_status == "verified_shared"
    assert report.location_shared is True
    assert report.readiness_score == 100
    assert report.status == "complete"
    assert "siap ditindaklanjuti" in reply


def test_ai_asks_only_the_structured_field_that_is_still_empty(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    report, reply = service.ingest(
        db,
        sender="farmer-one-gap",
        text=(
            "Desa: Sayung\nKecamatan: Sayung\nKabupaten: Demak\n"
            "Petani setempat: ya"
        ),
        image_url="https://example.com/1.jpg",
    )
    assert report.readiness_score == 69
    assert report.readiness_critique == [
        "deskripsi kejadian dan dampak belum cukup spesifik"
    ]
    assert "Ceritakan dampak" in reply
    assert "Desa/Kelurahan lokasi belum diketahui" not in reply
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")


def test_profile_persists_but_local_status_is_reconfirmed_for_each_report(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    first_text = (
        "Desa: Sayung\nKecamatan: Sayung\nKabupaten: Demak\n"
        "Deskripsi: Banjir merendam sawah dan merusak padi.\n"
        "Saya petani setempat dan bersedia dihubungi."
    )
    first, _ = service.ingest(
        db,
        sender="farmer-repeat",
        text=first_text,
        image_url="https://example.com/1.jpg",
    )
    assert first.status == "complete"

    second, reply = service.ingest(
        db,
        sender="farmer-repeat",
        text=(
            "Desa: Sayung\nKecamatan: Sayung\nKabupaten: Demak\n"
            "Deskripsi: Longsor menutup akses kebun dan merusak tanaman."
        ),
        image_url="https://example.com/a.jpg",
    )

    assert second.id != first.id
    assert second.status == "needs_follow_up"
    assert second.reporter_is_farmer is True
    assert second.reporter_is_local is None
    assert second.follow_up_available is True
    assert second.readiness_score == 69
    assert "petani atau penggarap" in reply

    second, reply = service.ingest(db, sender="farmer-repeat", text="ya")
    assert second.status == "complete"
    assert second.reporter_is_local is True
    assert second.readiness_score == 100
    assert "siap ditindaklanjuti" in reply
    assert db.query(FarmerProfile).count() == 1
    assert db.query(Report).count() == 2


def test_duplicate_evidence_does_not_increase_readiness(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    report, _ = service.ingest(
        db,
        sender="farmer-photo",
        text="LAPOR",
    )
    report, _ = service.ingest(
        db, sender="farmer-photo", text="", image_url="https://example.com/1.jpg"
    )
    score_after_first = report.readiness_score

    report, reply = service.ingest(
        db, sender="farmer-photo", text="", image_url="https://example.com/1.jpg"
    )

    assert len(report.evidence_urls) == 1
    assert report.readiness_score == score_after_first
    assert reply.startswith("Maaf, saya belum menangkap jawabannya")


def test_photo_is_mandatory_and_cannot_be_waived(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    report, reply = service.ingest(
        db,
        sender="farmer-no-photo",
        text=(
            "Desa: Sayung\n"
            "Kecamatan: Sayung\n"
            "Kabupaten: Demak\n"
            "Deskripsi: Banjir merendam sawah dan merusak tanaman.\n"
            "Petani setempat: ya"
        ),
    )

    assert report.status == "needs_follow_up"
    assert report.readiness_score == 69
    assert report.evidence_unavailable is False
    assert report.review_required is True
    assert "upload foto lokasi" in reply

    report, reply = service.ingest(
        db, sender="farmer-no-photo", text="tidak ada foto"
    )
    assert report.status == "needs_follow_up"
    assert report.evidence_urls == []
    assert reply.startswith("Foto bukti wajib")
    assert reply.endswith("Ketik BATAL untuk membatalkan laporan.")


def test_profile_facts_are_still_saved_when_provided(db):
    service = TriageService(
        classifier=MockClassifier(),
        geocoder=StubGeocoder(),
        privacy_consent_required=False,
    )
    report, reply = service.ingest(
        db,
        sender="farmer-negative",
        text=(
            "Desa: Sayung\nKecamatan: Sayung\nKabupaten: Demak\n"
            "Deskripsi: Banjir merendam sawah dan merusak tanaman.\n"
            "Status petani: tidak\nPetani setempat: tidak\nBisa dihubungi: tidak"
        ),
        image_url="https://example.com/1.jpg",
    )
    assert report.reporter_is_farmer is False
    assert report.reporter_is_local is False
    assert report.follow_up_available is False
    assert report.status == "complete"
    assert report.readiness_score == 100
    assert "siap ditindaklanjuti" in reply


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
        "village": "Sayung",
        "district": "Sayung",
        "regency": "Demak",
        "reporter_name": None,
        "is_farmer": None,
        "is_local_farmer": None,
        "home_location": None,
        "available_for_follow_up": None,
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
    assert result.village == "Sayung"
    assert result.source == "openrouter:openai/gpt-5-mini"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["extra_body"]["models"] == ["google/gemini-2.5-flash"]
    assert captured["extra_body"]["provider"]["data_collection"] == "deny"
    assert captured["messages"][1]["content"][1]["type"] == "image_url"
    assert "reporter_name" in captured["response_format"]["json_schema"]["schema"]["required"]


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
    profile = FarmerProfile(
        sender="whatsapp:+628123",
        name="Pak Budi",
        is_farmer=True,
        is_local_farmer=True,
        home_location="Sayung",
        available_for_follow_up=True,
        profile_summary="petani setempat; bersedia dihubungi",
    )
    report = Report(
        sender="whatsapp:+628123",
        text="banjir parah",
        incident_description="Sawah terdampak banjir parah.",
        image_url="https://example.com/private.jpg",
        evidence_urls=["https://example.com/private.jpg"],
        category="flood",
        severity="high",
        severity_confirmed=True,
        medical_needed=False,
        medical_status_confirmed=True,
        reporter_is_farmer=True,
        reporter_is_local=True,
        follow_up_available=True,
        needs=["pompa"],
        ai_summary="Sawah terdampak banjir.",
        ai_confidence=0.9,
        triage_source="heuristic",
        readiness_score=95,
        readiness_critique=[],
        status="complete",
        response_status="new",
        lat=-6.9201,
        lon=110.5199,
        location_verification_status="verified_geocoded",
        village="Sayung",
        district="Sayung",
        regency="Demak",
        location_label="RT 01 Sayung",
        region=region,
        farmer_profile=profile,
    )
    db.add_all([region, profile, report])
    db.commit()
    db.refresh(report)
    return region, report


def test_public_region_payload_has_no_reporter_photo_or_precise_pin(db):
    region, _ = _make_region_report(db)
    db.add_all(
        [
            LocalContact(
                name="Kantor Desa Sayung",
                type="desa",
                phone="+628111000102",
                lat=-6.9198,
                lon=110.5169,
            ),
            LocalContact(
                name="Puskesmas Sayung",
                type="puskesmas",
                phone="+62291686230",
                lat=-6.9200,
                lon=110.5170,
            ),
            LocalContact(
                name="Kantor Desa Terlalu Jauh",
                type="desa",
                phone="+628111999999",
                lat=-7.8014,
                lon=110.3648,
            ),
        ]
    )
    db.commit()
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
    assert responder["reports"][0]["readiness_score"] == 95
    assert responder["reports"][0]["village"] == "Sayung"
    assert responder["reports"][0]["farmer_profile"]["is_local_farmer"] is True
    assert [contact["name"] for contact in responder["nearest_contacts"]] == [
        "Kantor Desa Sayung"
    ]


def test_mediated_contact_is_removed_from_api_and_dashboard():
    assert all(
        route.path != "/api/reports/{report_id}/contact"
        for route in dashboard_api.router.routes
    )
    dashboard_html = Path("static/dashboard.html").read_text(encoding="utf-8")
    assert "Hubungi via sistem" not in dashboard_html
    assert "Kontak kantor desa terdekat" in dashboard_html


def test_weather_alert_targets_only_confirmed_local_reporters(db):
    region, local_report = _make_region_report(db)
    db.add(
        Report(
            sender="whatsapp:+628999",
            text="laporan saksi nonlokal",
            incident_description="Banjir terlihat dari perjalanan.",
            image_url="https://example.com/witness.jpg",
            evidence_urls=["https://example.com/witness.jpg"],
            village="Sayung",
            district="Sayung",
            regency="Demak",
            reporter_is_local=False,
            status="complete",
            readiness_score=100,
            lat=region.lat,
            lon=region.lon,
            region=region,
        )
    )
    db.commit()

    result = create_alert(
        AlertCreateIn(
            area_name="Sayung",
            lat=region.lat,
            lon=region.lon,
            radius_km=10,
            message="Waspada banjir susulan.",
            source="BMKG simulation",
        ),
        db,
    )

    assert result.delivery_count == 1
    deliveries = (
        db.query(OutboundMessage)
        .filter(OutboundMessage.kind == "weather_alert")
        .all()
    )
    assert [delivery.recipient for delivery in deliveries] == [local_report.sender]


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
