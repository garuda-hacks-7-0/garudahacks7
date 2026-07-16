from fastapi import APIRouter, Depends, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import IncomingReport, WebhookResponse
from app.services.triage import TriageService

router = APIRouter()
triage = TriageService()


@router.post("/webhooks/whatsapp", response_class=PlainTextResponse)
def whatsapp_webhook(
    From: str = Form(default="unknown"),
    Body: str = Form(default=""),
    MediaUrl0: str | None = Form(default=None),
    Latitude: float | None = Form(default=None),
    Longitude: float | None = Form(default=None),
    Address: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> str:
    report, reply = triage.ingest(
        db,
        sender=From,
        text=Body,
        image_url=MediaUrl0,
        lat=Latitude,
        lon=Longitude,
        location_label=Address,
    )
    return f"{reply}\n\n(report_id: {report.id})"


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

