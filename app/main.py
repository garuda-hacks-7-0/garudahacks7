from fastapi import FastAPI

app = FastAPI(title="WhatsApp Disaster Triage Mock")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
