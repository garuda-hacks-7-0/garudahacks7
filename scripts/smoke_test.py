"""End-to-end demo smoke test. Uses the configured database and no real providers."""

import asyncio
import os
from typing import Any, Callable

import httpx


async def main() -> None:
    if os.getenv("SMOKE_INLINE_SYNC") == "1":
        # Some restricted sandboxes cannot wake AnyIO worker threads. This keeps
        # the behavioral smoke test usable there without changing the app runtime.
        import anyio.to_thread
        import fastapi.routing

        async def run_inline(
            func: Callable[..., Any],
            *args: Any,
            abandon_on_cancel: bool = False,
            limiter: Any = None,
            **kwargs: Any,
        ) -> Any:
            return func(*args, **kwargs)

        anyio.to_thread.run_sync = run_inline
        fastapi.routing.run_in_threadpool = run_inline

    print("loading app", flush=True)
    from app.main import app

    print("starting app and seed", flush=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            await run_checks(client)


async def run_checks(client: httpx.AsyncClient) -> None:
    print("checking health and webhook", flush=True)
    health = await client.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}

    consent = await client.post(
        "/webhooks/whatsapp",
        data={
            "From": "demo-smoke-webhook",
            "Body": "SETUJU",
            "ButtonText": "SETUJU",
            "ButtonPayload": "CONSENT_ACCEPT",
        },
    )
    assert consent.status_code == 200

    webhook = await client.post(
            "/webhooks/whatsapp",
            data={
                "From": "demo-smoke-webhook",
                "Body": "banjir parah di Sayung Demak, ada warga luka perlu medis",
                "Latitude": "-6.9218",
                "Longitude": "110.5157",
                "Address": "Sayung, Demak",
            },
    )
    assert webhook.status_code == 200
    assert webhook.text.endswith("<Response/>")

    from app.db import SessionLocal
    from app.models import OutboundMessage

    db = SessionLocal()
    try:
        outbound = (
            db.query(OutboundMessage)
            .filter(
                OutboundMessage.recipient == "demo-smoke-webhook",
                OutboundMessage.kind == "intake_reply",
            )
            .order_by(OutboundMessage.id.desc())
            .first()
        )
        assert outbound is not None
        assert "Laporan TT-" in outbound.body
        assert "Nomor WhatsApp-mu tetap dirahasiakan" in outbound.body
    finally:
        db.close()

    public = await client.get(
        "/api/regions", params={"view": "public", "category": "flood"}
    )
    assert public.status_code == 200 and public.json()
    assert "reports" not in public.json()[0]

    print("checking privacy tiers and responder actions", flush=True)
    responder = await client.get(
        "/api/regions", params={"view": "responder", "category": "flood"}
    )
    assert responder.status_code == 200 and responder.json()[0]["reports"]
    report = responder.json()[0]["reports"][0]
    assert "sender" not in report
    assert report["reporter_alias"].startswith("Petani TT-")
    assert 0 <= report["readiness_score"] <= 100
    assert "farmer_profile" in report
    assert "farmer_profile" not in str(public.json())

    organizations = (await client.get("/api/organizations")).json()
    status = await client.post(
        f"/api/reports/{report['id']}/status",
        json={
            "status": "verified",
            "organization_id": organizations[0]["id"],
            "note": "Smoke test responder.",
        },
    )
    assert status.status_code == 200
    assert status.json()["notification_status"] == "simulated"

    print("checking AUTP and radius alert", flush=True)
    region = responder.json()[0]
    autp = await client.post(f"/api/regions/{region['id']}/autp-reminder")
    assert autp.status_code == 200
    assert autp.json()["matched_reporters"] >= 1

    alert = await client.post(
            "/api/admin/alerts",
            json={
                "area_name": "Sayung, Demak",
                "lat": -6.9218,
                "lon": 110.5157,
                "radius_km": 20,
                "message": "Waspada hujan ekstrem untuk smoke test.",
                "source": "BMKG simulation",
            },
    )
    assert alert.status_code == 200
    assert alert.json()["delivery_count"] >= 1

    dashboard = await client.get("/static/dashboard.html")
    assert dashboard.status_code == 200 and "View as" in dashboard.text

    print(
        {
            "health": health.json(),
            "consent": consent.status_code,
            "webhook": webhook.status_code,
            "public_regions": len(public.json()),
            "responder_regions": len(responder.json()),
            "status_notification": status.json()["notification_status"],
            "autp_reporters": autp.json()["matched_reporters"],
            "alert_deliveries": alert.json()["delivery_count"],
            "dashboard": dashboard.status_code,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
