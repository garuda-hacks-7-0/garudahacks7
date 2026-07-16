from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import dashboard, webhooks
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if get_settings().seed_demo_data:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(webhooks.router)
app.include_router(dashboard.router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

