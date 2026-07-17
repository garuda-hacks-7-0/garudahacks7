# Agent Guidance

This repository is a backend-first mock for a WhatsApp disaster triage demo. Keep changes small, swap-friendly, and centered on the integration points the demo already uses.

## Project Shape

- `app/main.py` wires the FastAPI app.
- `app/api/webhooks.py` handles WhatsApp/Twilio-style ingestion, offloading heavy processing (AI/geocoding) to a FastAPI background task to prevent webhook timeouts.
- `app/api/dashboard.py` serves dashboard-facing JSON, handles status updates, alerts, and crop insurance (AUTP) reminders.
- `app/services/triage.py` contains the main stateful triage service including privacy consent gating, form parsing, follow-up sequencing, and readiness score calculation.
- `app/services/classifier.py` connects to OpenRouter (using strict JSON schema models) for vision + text extraction, falling back to a deterministic classifier.
- `app/services/geocoder.py` resolves places using a local dictionary and dynamic fallback to OSM Nominatim API with administrative word cleaning.
- `app/services/notifications.py` handles Twilio WhatsApp outbound notifications and message persistence.
- `app/models.py`, `app/schemas.py`, and `app/db.py` define SQLite/Postgres persistence, schemas, and connection pools.

## Editing Rules

- Prefer the smallest change that fixes the request.
- Preserve the current mock architecture unless the user explicitly asks for a redesign.
- Treat external integrations as replaceable adapters: Twilio, Claude/GPT, BMKG, geocoding, and Postgres should remain easy to swap in later.
- Keep new endpoints and fields consistent with the existing dashboard and webhook flow.
- Avoid unnecessary abstractions, new frameworks, or broad refactors.

## Behavior Expectations

- **Privacy Consent Gate**: Senders must explicitly consent to privacy terms (`SETUJU`/`BATAL`) before any message content, media, or coordinates are persisted or sent to AI classifiers.
- **Stateful Ingestion & Follow-Ups**: Tracks incomplete reports using `ConversationState`. Calculates a `readiness_score` (0-100) based on fields like evidence, location, description, local farmer status, and needs. Prompts for missing fields sequentially if the score is under 70.
- **Dynamic Geocoding**: Resolves location labels using a local list or OpenStreetMap's Nominatim API with prefix cleaning (desa, kecamatan, etc.).
- **Dashboard Tiers**: Supports `public` vs `responder` views:
  - Public view only sees aggregated regional data (no sender info, precise GPS, or photos).
  - Responder view sees report details and local contacts (sender number is still masked).
- **BMKG Warnings & AUTP**: Supports simulated radius-based warning broadcasts and AUTP crop insurance follow-up reminders.

## Validation

- Use the repo README for the current run instructions and smoke tests.
- Run the test suite: `PYTHONPATH=. pytest` (or `.venv/bin/pytest`).
- Run the smoke test script: `DATABASE_URL=sqlite:// python -m scripts.smoke_test`.
- Prefer checking `/health`, webhook ingestion, and `/api/regions` responses after backend changes.

## Useful Files

- [README.md](README.md)
- [app/main.py](app/main.py)
- [app/api/webhooks.py](app/api/webhooks.py)
- [app/api/dashboard.py](app/api/dashboard.py)
- [app/services/triage.py](app/services/triage.py)
- [app/services/classifier.py](app/services/classifier.py)
- [app/services/geocoder.py](app/services/geocoder.py)
- [app/services/notifications.py](app/services/notifications.py)