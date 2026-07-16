# WhatsApp Disaster Triage Mock

Backend-first hackathon mock for collecting WhatsApp field reports, classifying them, enriching them with regional risk/resource context, and exposing dashboard-ready APIs.

## What is included

- FastAPI app with Twilio/WhatsApp-style webhook ingestion.
- Dead-simple follow-up flow:
  - asks for location when missing
  - asks severity when unclear
  - asks whether urgent medical help is needed
- Mock geocoding, weather risk, AI classification, and resource lookup services.
- SQLAlchemy models that work with SQLite locally and are Postgres-ready via `DATABASE_URL`.
- Dashboard JSON endpoints and a small static Leaflet mock.

## Run locally

```bash
python3.12 -m venv .venv312
source .venv312/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If `python3.12` is not on your PATH, use `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3` on this machine.

Open:

- API docs: <http://127.0.0.1:8000/docs>
- Demo dashboard: <http://127.0.0.1:8000/static/dashboard.html>

## Demo webhook calls

Twilio's WhatsApp sandbox posts form fields like `From`, `Body`, `MediaUrl0`, `Latitude`, and `Longitude`.

```bash
curl -X POST http://127.0.0.1:8000/webhooks/whatsapp \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'From=whatsapp:+6281234567890' \
  -d 'Body=sawah saya kebanjiran di Demak, air setinggi lutut'
```

Or use the JSON demo endpoint:

```bash
curl -X POST http://127.0.0.1:8000/demo/reports \
  -H 'Content-Type: application/json' \
  -d '{"sender":"whatsapp:+628111","text":"banjir besar di Demak, jalan putus, ada lansia sakit","image_url":"https://example.com/flooded-field.jpg"}'
```

## Dashboard filters

The dashboard calls `/api/regions` with filter query params:

```bash
curl 'http://127.0.0.1:8000/api/regions?urgency=medical&lat=-6.9218&lon=110.5157&max_distance_km=20'
```

Supported urgency values:

- `all`
- `medical`
- `critical`
- `high`
- `medium`

`max_distance_km` accepts `0` to `13000`. The browser dashboard uses live geolocation when the user allows it; otherwise it falls back to a demo operator location in Sayung.

## Swap points for real integrations

- WhatsApp/Twilio: `app/api/webhooks.py`
- AI structured extraction: `app/services/classifier.py`
- BMKG/weather enrichment: `app/services/weather.py`
- Geocoding: `app/services/geocoder.py`
- Health posts/relief inventory: `app/services/resources.py`
- Database/session settings: `app/db.py`
