from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncomingReport(BaseModel):
    sender: str = Field(default="demo-user")
    text: str = ""
    image_url: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    location_label: str | None = None


class WebhookResponse(BaseModel):
    reply: str
    report_id: int | None = None
    status: str


class OrganizationOut(BaseModel):
    id: int
    name: str
    type: str
    verified: bool
    applicant_kind: str = "organization"
    registration_status: str = "pending"
    email: str = ""
    phone: str = ""
    address: str = ""
    contact_name: str = ""
    contact_role: str = ""
    logo_url: str = ""
    website: str = ""
    operational_areas: list[str] = Field(default_factory=list)
    document_links: dict[str, str] = Field(default_factory=dict)
    verification_note: str = ""
    verified_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class OrganizationPublicOut(BaseModel):
    id: int
    name: str
    type: str
    verified: bool
    logo_url: str = ""
    contact_name: str = ""
    contact_role: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""

    model_config = {"from_attributes": True}


class OrganizationRegisterIn(BaseModel):
    applicant_kind: Literal["organization", "individual"]
    name: str = Field(min_length=2, max_length=140)
    type: str = Field(min_length=2, max_length=40)
    email: str = Field(min_length=5, max_length=160)
    phone: str = Field(min_length=8, max_length=40)
    address: str = Field(min_length=8, max_length=1000)
    contact_name: str = Field(min_length=2, max_length=140)
    contact_role: str = Field(min_length=2, max_length=100)
    logo_url: str = Field(default="", max_length=1000)
    website: str = Field(default="", max_length=300)
    operational_areas: list[str] = Field(min_length=1, max_length=20)
    document_links: dict[str, str] = Field(default_factory=dict)


class OrganizationVerificationIn(BaseModel):
    status: Literal["verified", "rejected"]
    note: str = Field(default="", max_length=1000)


class OrganizationVerificationResult(BaseModel):
    organization_id: int
    status: str
    verified: bool


class ReportUpdateOut(BaseModel):
    id: int
    status: str
    note: str
    organization_id: int
    organization_name: str
    organization_logo_url: str = ""
    organization_contact_name: str = ""
    organization_contact_role: str = ""
    organization_phone: str = ""
    organization_email: str = ""
    documentation_urls: list[str] = Field(default_factory=list)
    created_at: datetime


class PublicTrackingOrganizationOut(BaseModel):
    name: str
    type: str
    logo_url: str = ""
    contact_name: str = ""
    contact_role: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""


class PublicReportUpdateOut(BaseModel):
    id: int
    status: str
    note: str
    documentation_urls: list[str] = Field(default_factory=list)
    organization: PublicTrackingOrganizationOut
    created_at: datetime


class PublicReportTrackingOut(BaseModel):
    tracking_id: str
    incident_description: str
    ai_summary: str
    category: str
    severity: str
    needs: list[str] = Field(default_factory=list)
    response_status: str
    village: str
    district: str
    regency: str
    location_label: str | None
    evidence_urls: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    updates: list[PublicReportUpdateOut] = Field(default_factory=list)
    responsible_organization: PublicTrackingOrganizationOut | None = None


class FarmerProfileOut(BaseModel):
    name: str | None = None
    is_farmer: bool | None = None
    is_local_farmer: bool | None = None
    home_location: str | None = None
    available_for_follow_up: bool | None = None
    privacy_consent_at: datetime | None = None
    privacy_consent_version: str | None = None
    privacy_consent_method: str | None = None
    profile_summary: str = ""


class ReportOut(BaseModel):
    id: int
    reporter_alias: str
    text: str
    incident_description: str
    image_url: str | None
    evidence_urls: list[str] = Field(default_factory=list)
    evidence_count: int
    evidence_target: int
    evidence_unavailable: bool
    category: str
    severity: str
    medical_needed: bool
    needs: list[str] = Field(default_factory=list)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    field_confidence_reasons: dict[str, str] = Field(default_factory=dict)
    field_verification: dict[str, str] = Field(default_factory=dict)
    evidence_assessments: list[dict[str, object]] = Field(default_factory=list)
    verified_evidence_count: int = 0
    ai_summary: str
    ai_confidence: float
    triage_source: str
    review_required: bool
    readiness_score: int
    readiness_critique: list[str] = Field(default_factory=list)
    farmer_profile: FarmerProfileOut
    intake_status: str
    response_status: str
    lat: float | None
    lon: float | None
    location_shared: bool
    location_verification_status: str
    village: str
    district: str
    regency: str
    location_label: str | None
    created_at: datetime
    updates: list[ReportUpdateOut] = Field(default_factory=list)


class ResourceOut(BaseModel):
    id: int
    name: str
    kind: str
    lat: float
    lon: float
    stock_summary: str

    model_config = {"from_attributes": True}


class LocalContactOut(BaseModel):
    id: int
    name: str
    type: str
    phone: str | None
    lat: float
    lon: float
    distance_km: float


class RegionPublicOut(BaseModel):
    id: int
    name: str
    lat: float
    lon: float
    distance_km: float | None = None
    weather_risk: float
    report_risk: float
    risk_score: float
    last_summary: str
    report_count: int
    category_counts: dict[str, int]
    urgency_counts: dict[str, int]
    aggregate_needs: dict[str, int]
    progress: dict[str, int]


class RegionResponderOut(RegionPublicOut):
    reports: list[ReportOut] = Field(default_factory=list)
    nearest_resources: list[ResourceOut] = Field(default_factory=list)
    nearest_contacts: list[LocalContactOut] = Field(default_factory=list)


class ReportStatusUpdateIn(BaseModel):
    status: Literal["verified", "in_progress", "resolved", "rejected"]
    organization_id: int
    note: str = Field(default="", max_length=1000)
    documentation_urls: list[str] = Field(default_factory=list, max_length=10)


class ReportStatusUpdateResult(BaseModel):
    report_id: int
    response_status: str
    organization_name: str
    notification_status: str


class AlertCreateIn(BaseModel):
    area_name: str = Field(min_length=2, max_length=160)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(gt=0, le=500)
    message: str = Field(min_length=5, max_length=1200)
    source: str = Field(default="BMKG simulation", max_length=80)


class AlertOut(BaseModel):
    id: int
    area_name: str
    lat: float
    lon: float
    radius_km: float
    message: str
    source: str
    delivery_count: int
    delivery_statuses: dict[str, int]
    created_at: datetime


class BroadcastResult(BaseModel):
    region_id: int
    matched_reporters: int
    delivery_statuses: dict[str, int]
