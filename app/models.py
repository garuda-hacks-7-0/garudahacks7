from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ReportStatus(str, Enum):
    """Completeness of the WhatsApp intake conversation."""

    needs_follow_up = "needs_follow_up"
    complete = "complete"


class ResponseStatus(str, Enum):
    new = "new"
    verified = "verified"
    in_progress = "in_progress"
    resolved = "resolved"
    rejected = "rejected"


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    weather_risk: Mapped[float] = mapped_column(Float, default=0.0)
    report_risk: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_summary: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    reports: Mapped[list["Report"]] = relationship(back_populates="region")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(40))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    report_updates: Mapped[list["ReportUpdate"]] = relationship(back_populates="organization")


class ConversationState(Base):
    __tablename__ = "conversation_states"

    sender: Mapped[str] = mapped_column(String(80), primary_key=True, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    pending_fields: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    report: Mapped["Report"] = relationship()


class FarmerProfile(Base):
    """Private, persistent facts learned from a reporter across conversations."""

    __tablename__ = "farmer_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sender: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_farmer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_local_farmer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    home_location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    available_for_follow_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    privacy_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    privacy_consent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    privacy_consent_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profile_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    reports: Mapped[list["Report"]] = relationship(back_populates="farmer_profile")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sender: Mapped[str] = mapped_column(String(80), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    incident_description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evidence_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_unavailable: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    severity: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    severity_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    medical_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    medical_status_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reporter_is_farmer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reporter_is_local: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    follow_up_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    needs: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    triage_source: Mapped[str] = mapped_column(String(120), default="heuristic")
    review_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[ReportStatus] = mapped_column(
        String(30), default=ReportStatus.complete.value, index=True
    )
    response_status: Mapped[ResponseStatus] = mapped_column(
        String(30), default=ResponseStatus.new.value, index=True
    )
    follow_up_question: Mapped[str | None] = mapped_column(String(240), nullable=True)
    readiness_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    readiness_critique: Mapped[list[str]] = mapped_column(JSON, default=list)
    farmer_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("farmer_profiles.id"), nullable=True, index=True
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    location_verification_status: Mapped[str] = mapped_column(
        String(30), default="missing", index=True
    )
    village: Mapped[str] = mapped_column(String(160), default="")
    district: Mapped[str] = mapped_column(String(160), default="")
    regency: Mapped[str] = mapped_column(String(160), default="")
    location_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    region: Mapped[Region | None] = relationship(back_populates="reports")
    farmer_profile: Mapped[FarmerProfile | None] = relationship(back_populates="reports")
    updates: Mapped[list["ReportUpdate"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="ReportUpdate.created_at"
    )
    outbound_messages: Mapped[list["OutboundMessage"]] = relationship(back_populates="report")


class ReportUpdate(Base):
    __tablename__ = "report_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    report: Mapped[Report] = relationship(back_populates="updates")
    organization: Mapped[Organization] = relationship(back_populates="report_updates")


class LocalContact(Base):
    __tablename__ = "local_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(40), index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(140))
    kind: Mapped[str] = mapped_column(String(60))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    stock_summary: Mapped[str] = mapped_column(Text, default="")


class InboundMessage(Base):
    __tablename__ = "inbound_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender: Mapped[str] = mapped_column(String(80), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    media_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    button_payload: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id"), nullable=True, index=True
    )
    recipient: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(Text)
    delivery_status: Mapped[str] = mapped_column(String(30), default="simulated")
    provider_sid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    report: Mapped[Report | None] = relationship(back_populates="outbound_messages")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    area_name: Mapped[str] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(80), default="BMKG simulation")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    recipient: Mapped[str] = mapped_column(String(80), index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    provider_sid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alert: Mapped[Alert] = relationship(back_populates="deliveries")
