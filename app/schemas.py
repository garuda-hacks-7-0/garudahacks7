from datetime import datetime

from pydantic import BaseModel, Field


class IncomingReport(BaseModel):
    sender: str = Field(default="demo-user")
    text: str = ""
    image_url: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_label: str | None = None


class WebhookResponse(BaseModel):
    reply: str
    report_id: int | None = None
    status: str


class ReportOut(BaseModel):
    id: int
    sender: str
    text: str
    image_url: str | None
    category: str
    severity: str
    medical_needed: bool
    status: str
    lat: float | None
    lon: float | None
    location_label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResourceOut(BaseModel):
    id: int
    name: str
    kind: str
    lat: float
    lon: float
    stock_summary: str

    model_config = {"from_attributes": True}


class RegionOut(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    distance_km: float | None = None
    weather_risk: float
    report_risk: float
    risk_score: float
    last_summary: str
    reports: list[ReportOut] = []
    nearest_resources: list[ResourceOut] = []

    model_config = {"from_attributes": True}
