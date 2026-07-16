from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import OutboundMessage


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    provider_sid: str | None = None


class WhatsAppNotifier:
    """Twilio outbound adapter. Missing credentials intentionally mean demo mode."""

    def __init__(self, settings: Settings | None = None, client: object | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.twilio_account_sid
            and self.settings.twilio_auth_token
            and self.settings.twilio_whatsapp_from
        )

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    def send(self, recipient: str, body: str) -> DeliveryResult:
        if not self.enabled or recipient.startswith("seed-") or "demo" in recipient:
            return DeliveryResult(status="simulated")

        try:
            message = self._get_client().messages.create(
                from_=self.settings.twilio_whatsapp_from,
                to=recipient,
                body=body,
            )
            return DeliveryResult(status="sent", provider_sid=message.sid)
        except Exception:
            logger.exception("Twilio WhatsApp delivery failed")
            return DeliveryResult(status="failed")


class NotificationService:
    def __init__(self, notifier: WhatsAppNotifier | None = None) -> None:
        self.notifier = notifier or WhatsAppNotifier()

    def send(
        self,
        db: Session,
        *,
        recipient: str,
        body: str,
        kind: str,
        report_id: int | None = None,
    ) -> OutboundMessage:
        result = self.notifier.send(recipient, body)
        record = OutboundMessage(
            report_id=report_id,
            recipient=recipient,
            kind=kind,
            body=body,
            delivery_status=result.status,
            provider_sid=result.provider_sid,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
