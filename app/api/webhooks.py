import logging
import re
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Report
from app.schemas import IncomingReport, WebhookResponse
from app.services.notifications import NotificationService
from app.services.triage import (
    FORM_REQUIRED_MESSAGE,
    LOCATION_CHECK_MESSAGE,
    PRIVACY_CONSENT_ACCEPTED,
    PRIVACY_CONSENT_DECLINED,
    PRIVACY_CONSENT_PROMPT,
    TriageService,
    WELCOME_MESSAGE,
)

router = APIRouter()
triage = TriageService(form_required=True)
demo_triage = TriageService(
    privacy_consent_required=False,
    form_required=False,
)
notifications = NotificationService()
settings = get_settings()
logger = logging.getLogger(__name__)
_sender_locks: dict[str, Lock] = {}
_sender_locks_guard = Lock()


def _twilio_message_response(message: str) -> Response:
    escaped = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escaped}</Message></Response>"
    )
    return Response(content=xml, media_type="text/xml")


def _empty_twilio_response() -> Response:
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
        media_type="text/xml",
    )


def _lock_for_sender(sender: str) -> Lock:
    with _sender_locks_guard:
        return _sender_locks.setdefault(sender, Lock())


def _should_send_location_update(
    body: str, latitude: float | None, longitude: float | None
) -> bool:
    if latitude is not None and longitude is not None:
        return True
    lower = body.lower()
    return bool(
        re.search(r"\bform\s+laporan(?:\s+petani)?\b", lower)
        and any(
            label in lower
            for label in ["desa/kelurahan:", "kecamatan:", "kota/kabupaten:"]
        )
    )


def _process_whatsapp_message(
    sender: str,
    body: str,
    image_urls: list[str],
    latitude: float | None,
    longitude: float | None,
    address: str | None,
    button_payload: str | None = None,
) -> None:
    """Run slow AI triage after Twilio has received its immediate HTTP 200."""
    with _lock_for_sender(sender):
        db = SessionLocal()
        try:
            if (
                _should_send_location_update(body, latitude, longitude)
                and triage.has_current_privacy_consent(db, sender)
            ):
                notifications.send(
                    db,
                    recipient=sender,
                    body=LOCATION_CHECK_MESSAGE,
                    kind="processing_update",
                )
            report, reply = triage.ingest(
                db,
                sender=sender,
                text=body,
                image_urls=image_urls,
                lat=latitude,
                lon=longitude,
                location_label=address,
                button_payload=button_payload,
            )
            candidate_id = getattr(report, "id", None)
            stored_report = db.get(Report, candidate_id) if candidate_id else None
            is_consent_prompt = reply == PRIVACY_CONSENT_PROMPT
            is_pre_consent_reply = is_consent_prompt or reply == PRIVACY_CONSENT_DECLINED
            is_form_prompt = reply in {
                PRIVACY_CONSENT_ACCEPTED,
                WELCOME_MESSAGE,
                FORM_REQUIRED_MESSAGE,
            }
            notifications.send(
                db,
                recipient=sender,
                body=reply,
                kind="privacy_consent" if is_pre_consent_reply else "intake_reply",
                report_id=stored_report.id if stored_report else None,
                content_sid=(
                    settings.twilio_consent_content_sid
                    if is_consent_prompt
                    else (
                        settings.twilio_form_content_sid
                        if is_form_prompt
                        else None
                    )
                ),
                persist=not is_pre_consent_reply,
            )
        except Exception:
            db.rollback()
            logger.exception("Background WhatsApp triage failed")
            notifications.send(
                db,
                recipient=sender,
                body="Maaf, laporanmu belum berhasil diproses. Coba kirim sekali lagi ya.",
                kind="intake_error",
                persist=False,
            )
        finally:
            db.close()


@router.post("/webhooks/whatsapp")
def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    from_number: str = Form(default="unknown", alias="From"),
    body: str = Form(default="", alias="Body"),
    media_url_0: str | None = Form(default=None, alias="MediaUrl0"),
    media_url_1: str | None = Form(default=None, alias="MediaUrl1"),
    media_url_2: str | None = Form(default=None, alias="MediaUrl2"),
    latitude: float | None = Form(default=None, alias="Latitude"),
    longitude: float | None = Form(default=None, alias="Longitude"),
    address: str | None = Form(default=None, alias="Address"),
    label: str | None = Form(default=None, alias="Label"),
    button_text: str | None = Form(default=None, alias="ButtonText"),
    button_payload: str | None = Form(default=None, alias="ButtonPayload"),
) -> Response:
    payload = button_payload if isinstance(button_payload, str) else None
    button_label = button_text if isinstance(button_text, str) else None
    message_body = body if isinstance(body, str) else ""
    canonical_body = {
        "CONSENT_ACCEPT": "SETUJU",
        "CONSENT_CANCEL": "BATAL",
        "FORM_COPY": "SALIN FORM",
    }.get((payload or "").strip().upper(), message_body or button_label or "")
    location_label = address or label
    background_tasks.add_task(
        _process_whatsapp_message,
        from_number,
        canonical_body,
        [url for url in [media_url_0, media_url_1, media_url_2] if url],
        latitude,
        longitude,
        location_label,
        payload,
    )
    return _empty_twilio_response()


@router.post("/demo/reports", response_model=WebhookResponse)
def demo_report(payload: IncomingReport, db: Session = Depends(get_db)) -> WebhookResponse:
    report, reply = demo_triage.ingest(
        db,
        sender=payload.sender,
        text=payload.text,
        image_url=payload.image_url,
        lat=payload.lat,
        lon=payload.lon,
        location_label=payload.location_label,
    )
    if report is None:
        return WebhookResponse(reply=reply, report_id=None, status="idle")
    return WebhookResponse(reply=reply, report_id=report.id, status=report.status)
