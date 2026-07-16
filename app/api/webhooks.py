from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import IncomingReport, WebhookResponse
from app.services.triage import TriageService

router = APIRouter()
triage = TriageService()


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


@router.post("/webhooks/whatsapp")
def whatsapp_webhook(
    from_number: str = Form(default="unknown", alias="From"),
    body: str = Form(default="", alias="Body"),
    media_url_0: str | None = Form(default=None, alias="MediaUrl0"),
    latitude: float | None = Form(default=None, alias="Latitude"),
    longitude: float | None = Form(default=None, alias="Longitude"),
    address: str | None = Form(default=None, alias="Address"),
    db: Session = Depends(get_db),
) -> Response:
    _, reply = triage.ingest(
        db,
        sender=from_number,
        text=body,
        image_url=media_url_0,
        lat=latitude,
        lon=longitude,
        location_label=address,
    )
    return _twilio_message_response(reply)


@router.post("/demo/reports", response_model=WebhookResponse)
def demo_report(payload: IncomingReport, db: Session = Depends(get_db)) -> WebhookResponse:
    report, reply = triage.ingest(
        db,
        sender=payload.sender,
        text=payload.text,
        image_url=payload.image_url,
        lat=payload.lat,
        lon=payload.lon,
        location_label=payload.location_label,
    )
    return WebhookResponse(reply=reply, report_id=report.id, status=report.status)
