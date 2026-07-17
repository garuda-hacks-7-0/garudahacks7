from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
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


@app.get("/", include_in_schema=False)
def landing_page() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/map", include_in_schema=False)
def map_page() -> FileResponse:
    return FileResponse("static/dashboard.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse("static/login.html")


@app.get("/reports", include_in_schema=False)
def reports_page() -> FileResponse:
    return FileResponse("static/reports.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
