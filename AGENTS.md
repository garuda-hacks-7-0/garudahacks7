# Agent Guidance

This repository is a backend-first mock for a WhatsApp disaster triage demo. Keep changes small, swap-friendly, and centered on the integration points the demo already uses.

## Project Shape

- `app/main.py` wires the FastAPI app.
- `app/api/webhooks.py` handles WhatsApp/Twilio-style ingestion.
- `app/api/dashboard.py` serves dashboard-facing JSON.
- `app/services/` contains mock classifier, geocoder, weather, triage, and resource logic.
- `app/models.py`, `app/schemas.py`, and `app/db.py` define persistence and API shapes.
- `static/dashboard.html` is the simple Leaflet demo UI.

## Editing Rules

- Prefer the smallest change that fixes the request.
- Preserve the current mock architecture unless the user explicitly asks for a redesign.
- Treat external integrations as replaceable adapters: Twilio, Claude/GPT, BMKG, geocoding, and Postgres should remain easy to swap in later.
- Keep new endpoints and fields consistent with the existing dashboard and webhook flow.
- Avoid unnecessary abstractions, new frameworks, or broad refactors.

## Behavior Expectations

- **Stateful Ingestion**: Ingestion uses `ConversationState` records to preserve per-sender context between webhook events, prompting for missing fields sequentially (location -> severity -> medical need) rather than restarting the flow.
- **Dynamic Geocoding**: The geocoding service resolves coordinates using a hardcoded local list as a fast lookup, falling back dynamically to OpenStreetMap's Nominatim API for arbitrary location strings (e.g., "Aceh"). It cleans Indonesian administrative prefix words (e.g. "desa", "kecamatan") and applies custom regex candidate extraction.
- **Conversation Cancellation**: Senders can text abort keywords (`"batal"`, `"cancel"`, `"abort"`, `"reset"`) to clear active conversation states and delete incomplete reports, starting clean on their next message.
- **Mock/Heuristic Classifier**: The classifier in `app/services/classifier.py` uses heuristic keyword matching to mock LLM-structured outputs. This ensures deterministic behavior and saves API credits during demos. Do not introduce actual LLM API calls (e.g. OpenAI/Claude) unless explicitly requested.
- Dashboard filters should continue to support urgency and distance-based scoping.
- If live location is relevant, prefer browser geolocation on the frontend and keep a safe fallback location for demos.
- Severity, urgency, and resource summaries should remain deterministic enough for hackathon demos unless the task explicitly asks for real model calls.

## Validation

- Use the repo README for the current run instructions and smoke tests.
- Prefer checking `/health`, webhook ingestion, and `/api/regions` responses after backend changes.
- Keep validation targeted to the files and endpoints you touched.

## Useful Files

- [README.md](README.md)
- [app/main.py](app/main.py)
- [app/api/webhooks.py](app/api/webhooks.py)
- [app/api/dashboard.py](app/api/dashboard.py)
- [app/services/classifier.py](app/services/classifier.py)
- [app/services/geocoder.py](app/services/geocoder.py)
- [app/services/weather.py](app/services/weather.py)
- [app/services/resources.py](app/services/resources.py)