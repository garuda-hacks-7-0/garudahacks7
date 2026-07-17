"""Create the Twilio Quick Reply content used by the privacy-consent gate."""

import httpx

from app.config import get_settings
from app.services.triage import PRIVACY_CONSENT_PROMPT


def main() -> None:
    settings = get_settings()
    if settings.twilio_consent_content_sid:
        print(f"TWILIO_CONSENT_CONTENT_SID={settings.twilio_consent_content_sid}")
        return
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise SystemExit(
            "Isi TWILIO_ACCOUNT_SID dan TWILIO_AUTH_TOKEN di .env terlebih dahulu."
        )

    response = httpx.post(
        "https://content.twilio.com/v1/Content",
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        json={
            "friendly_name": "petanih_privacy_consent_v1",
            "language": "id",
            "types": {
                "twilio/quick-reply": {
                    "body": PRIVACY_CONSENT_PROMPT,
                    "actions": [
                        {"title": "SETUJU", "id": "CONSENT_ACCEPT"},
                        {"title": "BATAL", "id": "CONSENT_CANCEL"},
                    ],
                }
            },
        },
        timeout=20,
    )
    response.raise_for_status()
    content_sid = response.json()["sid"]
    print(f"TWILIO_CONSENT_CONTENT_SID={content_sid}")


if __name__ == "__main__":
    main()
