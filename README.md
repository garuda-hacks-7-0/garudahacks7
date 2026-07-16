# TanggapTani

Demo disaster-information layer untuk laporan bencana pertanian melalui WhatsApp. Satu laporan petani masuk ke peta publik dalam bentuk agregat dan ke dashboard responder dengan detail operasional, lalu setiap perubahan status dikirim kembali kepada petani dengan nama organisasi penindak lanjut.

Repo ini tetap memakai arsitektur FastAPI + SQLAlchemy + Leaflet yang sudah ada. Integrasi eksternal dibuat sebagai adapter agar OpenRouter, Twilio, BMKG, dan database dapat diganti tanpa mengubah alur triase.

## Cakupan PRD v2

- WhatsApp/Twilio-style intake dengan percakapan stateful: lokasi → keparahan → kebutuhan medis.
- Ack berisi ID laporan dan consent notice.
- OpenRouter vision + structured JSON extraction dengan model fallback; classifier heuristik dipakai saat key tidak tersedia atau provider gagal.
- Persistence untuk laporan, inbound/outbound message, organization, local contact, status update, alert, dan alert delivery.
- Tiered API dan satu dashboard dengan toggle `Publik`/`Responder`.
  - Publik hanya menerima cluster/agregat; tidak menerima sender, GPS presisi, foto, atau action.
  - Responder menerima report detail dan local contact, tetapi tetap tidak pernah menerima nomor reporter.
- Status update menyimpan organisasi pelaku dan mengirim notifikasi WA bernama organisasi.
- System-mediated contact tanpa mengekspos nomor reporter.
- Simulasi warning BMKG berbasis radius dan delivery log.
- AUTP follow-up untuk cluster banjir terverifikasi.
- 24 seeded reports, 4 verified organizations, local contacts, dan resources.
- Peta auto-refresh 10 detik, region clustering, filter, live operator location, status action, admin alert, dan demo report.

## Menjalankan lokal

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Buka:

- Dashboard: <http://127.0.0.1:8000/static/dashboard.html>
- API docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

SQLite dan seed data langsung bekerja tanpa kredensial. Jika repo pernah dijalankan pada schema lama, startup akan menambah kolom SQLite demo yang baru. Deployment Postgres tetap harus memakai migration formal.

## Mengaktifkan AI OpenRouter

Isi `.env`:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-5-mini
OPENROUTER_FALLBACK_MODELS=google/gemini-2.5-flash
APP_PUBLIC_URL=https://domain-demo-kamu.example
```

Classifier mengirim teks dan foto (jika ada), meminta strict JSON schema, meminta provider yang mendukung parameter tersebut, dan menolak data collection provider melalui routing preference. Media Twilio yang terlindungi akan diunduh server-side menggunakan kredensial Twilio lalu dikirim sebagai data URL; URL umum diteruskan langsung.

Jika API key kosong atau request gagal, `triage_source` akan menjadi `heuristic`/`heuristic_fallback`; demo tidak berhenti dan tidak memakai kredit.

## Mengaktifkan Twilio WhatsApp

Isi `.env`:

```dotenv
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

Expose server dengan ngrok lalu pasang webhook Sandbox ke:

```text
POST https://<subdomain-ngrok>/webhooks/whatsapp
```

Tanpa tiga value Twilio di atas, outbound status/alert/AUTP tetap disimpan dengan status `simulated`. Nomor seed dan nomor yang mengandung `demo` juga sengaja tidak dikirim ke Twilio.

WhatsApp membatasi free-form outbound message pada customer-service window. Untuk produksi, gunakan approved WhatsApp sender dan template yang sesuai; Sandbox hanya mengirim ke nomor yang sudah join.

## Smoke test

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/demo/reports \
  -H 'Content-Type: application/json' \
  -d '{"sender":"demo-smoke","text":"banjir parah di Sayung Demak, ada warga luka perlu medis","lat":-6.9218,"lon":110.5157,"location_label":"Sayung, Demak"}'

curl 'http://127.0.0.1:8000/api/regions?view=public&category=flood&hours=720'

curl 'http://127.0.0.1:8000/api/regions?view=responder&urgency=medical&lat=-6.9218&lon=110.5157&max_distance_km=20'
```

Test suite:

```bash
pytest -q
DATABASE_URL=sqlite:// python -m scripts.smoke_test
```

## Endpoint demo utama

- `POST /webhooks/whatsapp` — Twilio form webhook.
- `POST /demo/reports` — JSON intake tanpa Twilio.
- `GET /api/regions?view=public|responder` — payload benar-benar berbeda per tier.
- `GET /api/reports/{id}?view=responder` — detail operasional tanpa nomor reporter.
- `POST /api/reports/{id}/status` — update status + org identity + WA notification.
- `POST /api/reports/{id}/contact` — pesan system-mediated ke reporter.
- `POST /api/regions/{id}/autp-reminder` — follow-up AUTP setelah flood report diverifikasi.
- `POST /api/admin/alerts` — warning berbasis lat/lon/radius.
- `GET /api/admin/alerts` — delivery history agregat.

## TODO pemilik repo sebelum demo nyata

- Buat OpenRouter API key, isi saldo/budget limit, lalu isi `OPENROUTER_API_KEY`.
- Aktifkan Twilio WhatsApp Sandbox, join dari nomor demo, isi tiga env Twilio, dan pasang URL webhook ngrok.
- Ganti nomor local contact seed dengan nomor posko/desa/puskesmas yang memang menyetujui publikasi.
- Jalankan seeded evaluation untuk category + urgency dan pastikan akurasi ≥90% sebelum klaim di deck.
- Konfirmasi ulang copy AUTP dengan PPL/dinas lokal dan ketentuan polis yang dipakai reporter. Reminder saat ini mengikuti PRD: lapor ≤7 hari, pertanggungan hingga Rp6 juta/ha, dan kerusakan minimal 75% bila syarat polis terpenuhi.
- Untuk deployment: pindahkan `DATABASE_URL` ke managed Postgres/Supabase, buat migration formal, pakai PostGIS untuk radius/nearest query, dan aktifkan Realtime atau SSE. SQLite + polling 10 detik hanya ditujukan untuk demo.
- Tambahkan validasi `X-Twilio-Signature`, real auth/RLS, organization vetting, rate limit/spam protection, dan approved WA templates sebelum production.
- BMKG masih simulated sesuai scope Should; live polling dan KATAM advisory tetap roadmap.

## Swap points

- AI structured extraction: `app/services/classifier.py`
- WhatsApp outbound/logging: `app/services/notifications.py`
- WhatsApp inbound: `app/api/webhooks.py`
- Status, privacy tiers, alert, AUTP: `app/api/dashboard.py`
- Geocoding: `app/services/geocoder.py`
- Weather/BMKG: `app/services/weather.py`
- Database models: `app/models.py`
