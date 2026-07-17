from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import (
    Alert,
    AlertDelivery,
    Organization,
    Region,
    Report,
    ReportUpdate,
)
from app.schemas import (
    AlertCreateIn,
    AlertOut,
    BroadcastResult,
    FarmerProfileOut,
    LocalContactOut,
    OrganizationOut,
    RegionPublicOut,
    RegionResponderOut,
    ReportOut,
    ReportStatusUpdateIn,
    ReportStatusUpdateResult,
    ReportUpdateOut,
)
from app.services.classifier import SEVERITY_ORDER
from app.services.notifications import NotificationService
from app.services.resources import ResourceService, km_between
from app.services.triage import EVIDENCE_TARGET


router = APIRouter(prefix="/api")
resources = ResourceService()
notifications = NotificationService()


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return (
        db.query(Organization)
        .filter(Organization.verified.is_(True))
        .order_by(Organization.name)
        .all()
    )


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    view: str = Query(default="responder", pattern="^responder$"),
    urgency: str = Query(
        default="all", pattern="^(all|medical|critical|high|medium)$"
    ),
    response_status: str = Query(
        default="all",
        pattern="^(all|new|verified|in_progress|resolved|rejected)$",
    ),
    review_required: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    query = db.query(Report).options(
        selectinload(Report.updates).selectinload(ReportUpdate.organization)
    )
    if response_status != "all":
        query = query.filter(Report.response_status == response_status)
    if review_required is not None:
        query = query.filter(Report.review_required.is_(review_required))
    reports = query.order_by(Report.created_at.desc()).limit(200).all()
    return [
        _report_out(report)
        for report in reports
        if _report_matches_urgency(report, urgency)
    ]


@router.get("/reports/{report_id}", response_model=ReportOut)
def report_detail(
    report_id: int,
    view: str = Query(default="responder", pattern="^responder$"),
    db: Session = Depends(get_db),
) -> ReportOut:
    report = (
        db.query(Report)
        .options(selectinload(Report.updates).selectinload(ReportUpdate.organization))
        .filter(Report.id == report_id)
        .one_or_none()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_out(report)


@router.post(
    "/reports/{report_id}/status", response_model=ReportStatusUpdateResult
)
def update_report_status(
    report_id: int,
    payload: ReportStatusUpdateIn,
    db: Session = Depends(get_db),
) -> ReportStatusUpdateResult:
    report = db.query(Report).filter(Report.id == report_id).one_or_none()
    organization = (
        db.query(Organization)
        .filter(
            Organization.id == payload.organization_id,
            Organization.verified.is_(True),
        )
        .one_or_none()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if organization is None:
        raise HTTPException(status_code=400, detail="Verified organization is required")

    report.response_status = payload.status
    update = ReportUpdate(
        report=report,
        status=payload.status,
        note=payload.note.strip(),
        organization=organization,
    )
    db.add_all([report, update])
    db.commit()

    status_phrase = {
        "verified": "diverifikasi",
        "in_progress": "mulai ditangani",
        "resolved": "ditandai selesai",
        "rejected": "dikembalikan untuk pemeriksaan ulang",
    }[payload.status]
    message = (
        f"Update TT-{report.id:04d}: laporan Anda {status_phrase} oleh "
        f"{organization.name}."
    )
    if payload.note.strip():
        message += f" Catatan: {payload.note.strip()}"
    delivery = notifications.send(
        db,
        recipient=report.sender,
        body=message,
        kind="status_update",
        report_id=report.id,
    )
    return ReportStatusUpdateResult(
        report_id=report.id,
        response_status=payload.status,
        organization_name=organization.name,
        notification_status=delivery.delivery_status,
    )


@router.get("/regions", response_model=None)
def list_regions(
    view: str = Query(default="public", pattern="^(public|responder)$"),
    urgency: str = Query(
        default="all", pattern="^(all|medical|critical|high|medium)$"
    ),
    category: str = Query(default="all", max_length=80),
    hours: int = Query(default=720, ge=1, le=8760),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    max_distance_km: float = Query(default=13000, ge=0, le=13000),
    db: Session = Depends(get_db),
) -> list[RegionPublicOut | RegionResponderOut]:
    regions = (
        db.query(Region)
        .options(
            selectinload(Region.reports)
            .selectinload(Report.updates)
            .selectinload(ReportUpdate.organization)
        )
        .order_by(Region.risk_score.desc())
        .all()
    )
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    output: list[RegionPublicOut | RegionResponderOut] = []
    for region in regions:
        matching_reports = [
            report
            for report in region.reports
            if report.created_at >= cutoff
            and (category == "all" or report.category == category)
            and _report_matches_urgency(report, urgency)
        ]
        if not matching_reports:
            continue

        distance_km = None
        if lat is not None and lon is not None:
            distance_km = round(km_between(lat, lon, region.lat, region.lon), 1)
            if distance_km > max_distance_km:
                continue

        base = _region_aggregate(region, matching_reports, distance_km)
        if view == "public":
            base["lat"] = round(region.lat, 2)
            base["lon"] = round(region.lon, 2)
            output.append(RegionPublicOut(**base))
            continue

        nearest_contacts = []
        for contact in resources.nearest_contacts(
            db,
            region.lat,
            region.lon,
            limit=3,
            contact_type="desa",
            max_distance_km=50,
        ):
            nearest_contacts.append(
                LocalContactOut(
                    id=contact.id,
                    name=contact.name,
                    type=contact.type,
                    phone=contact.phone,
                    lat=contact.lat,
                    lon=contact.lon,
                    distance_km=round(
                        km_between(region.lat, region.lon, contact.lat, contact.lon), 1
                    ),
                )
            )
        output.append(
            RegionResponderOut(
                **base,
                reports=[_report_out(report) for report in matching_reports],
                nearest_resources=resources.nearest(
                    db, region.lat, region.lon, limit=3
                ),
                nearest_contacts=nearest_contacts,
            )
        )
    return output


@router.get("/regions/{region_id}", response_model=None)
def region_detail(
    region_id: int,
    view: str = Query(default="public", pattern="^(public|responder)$"),
    db: Session = Depends(get_db),
) -> RegionPublicOut | RegionResponderOut:
    region = (
        db.query(Region)
        .options(
            selectinload(Region.reports)
            .selectinload(Report.updates)
            .selectinload(ReportUpdate.organization)
        )
        .filter(Region.id == region_id)
        .one_or_none()
    )
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found")
    base = _region_aggregate(region, region.reports, None)
    if view == "public":
        base["lat"] = round(region.lat, 2)
        base["lon"] = round(region.lon, 2)
        return RegionPublicOut(**base)
    contacts = [
        LocalContactOut(
            id=contact.id,
            name=contact.name,
            type=contact.type,
            phone=contact.phone,
            lat=contact.lat,
            lon=contact.lon,
            distance_km=round(
                km_between(region.lat, region.lon, contact.lat, contact.lon), 1
            ),
        )
        for contact in resources.nearest_contacts(
            db,
            region.lat,
            region.lon,
            limit=3,
            contact_type="desa",
            max_distance_km=50,
        )
    ]
    return RegionResponderOut(
        **base,
        reports=[_report_out(report) for report in region.reports],
        nearest_resources=resources.nearest(db, region.lat, region.lon, limit=3),
        nearest_contacts=contacts,
    )


@router.post("/regions/{region_id}/autp-reminder", response_model=BroadcastResult)
def send_autp_reminder(
    region_id: int, db: Session = Depends(get_db)
) -> BroadcastResult:
    region = (
        db.query(Region)
        .options(selectinload(Region.reports))
        .filter(Region.id == region_id)
        .one_or_none()
    )
    if region is None:
        raise HTTPException(status_code=404, detail="Region not found")
    flood_reports = [report for report in region.reports if report.category == "flood"]
    if not any(
        report.response_status in {"verified", "in_progress", "resolved"}
        for report in flood_reports
    ):
        raise HTTPException(
            status_code=409,
            detail="Verify at least one flood report before sending an AUTP reminder",
        )

    nearest = resources.nearest_contacts(
        db,
        region.lat,
        region.lon,
        limit=1,
        contact_type="desa",
        max_distance_km=50,
    )
    contact_text = "Hubungi PPL atau dinas pertanian setempat."
    if nearest:
        contact_text = f"Titik bantuan terdekat: {nearest[0].name}"
        if nearest[0].phone:
            contact_text += f" ({nearest[0].phone})"
        contact_text += "."
    body = (
        f"Pengingat pascabencana {region.name}: bila sawah Anda terdaftar AUTP, laporkan "
        "indikasi kerusakan kepada PPL/POPT-PHP dan petugas asuransi maksimal 7 hari kalender. "
        "Pertanggungan dapat mencapai Rp6 juta/ha bila syarat polis terpenuhi, termasuk "
        "intensitas kerusakan minimal 75%. Simpan foto, lokasi, dan waktu kejadian. "
        f"{contact_text}"
    )
    unique_reports = {
        report.sender: report
        for report in flood_reports
        if report.reporter_is_local is True
    }
    statuses: Counter[str] = Counter()
    for report in unique_reports.values():
        delivery = notifications.send(
            db,
            recipient=report.sender,
            body=body,
            kind="autp_reminder",
            report_id=report.id,
        )
        statuses[delivery.delivery_status] += 1
    return BroadcastResult(
        region_id=region.id,
        matched_reporters=len(unique_reports),
        delivery_statuses=dict(statuses),
    )


@router.post("/admin/alerts", response_model=AlertOut)
def create_alert(
    payload: AlertCreateIn, db: Session = Depends(get_db)
) -> AlertOut:
    alert = Alert(**payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)

    candidates = (
        db.query(Report)
        .filter(
            Report.lat.is_not(None),
            Report.lon.is_not(None),
            Report.reporter_is_local.is_(True),
        )
        .order_by(Report.created_at.desc())
        .all()
    )
    matched: dict[str, Report] = {}
    for report in candidates:
        if (
            report.sender not in matched
            and km_between(payload.lat, payload.lon, report.lat, report.lon)
            <= payload.radius_km
        ):
            matched[report.sender] = report

    body = f"⚠️ {payload.source} — {payload.area_name}: {payload.message}"
    for report in matched.values():
        delivery = notifications.send(
            db,
            recipient=report.sender,
            body=body,
            kind="weather_alert",
            report_id=report.id,
        )
        db.add(
            AlertDelivery(
                alert_id=alert.id,
                recipient=report.sender,
                report_id=report.id,
                status=delivery.delivery_status,
                provider_sid=delivery.provider_sid,
            )
        )
    db.commit()
    db.refresh(alert)
    return _alert_out(alert)


@router.get("/admin/alerts", response_model=list[AlertOut])
def list_alerts(db: Session = Depends(get_db)) -> list[AlertOut]:
    alerts = (
        db.query(Alert)
        .options(selectinload(Alert.deliveries))
        .order_by(Alert.created_at.desc())
        .limit(50)
        .all()
    )
    return [_alert_out(alert) for alert in alerts]


def _report_out(report: Report) -> ReportOut:
    updates = [
        ReportUpdateOut(
            id=update.id,
            status=update.status,
            note=update.note,
            organization_id=update.updated_by,
            organization_name=update.organization.name,
            created_at=update.created_at,
        )
        for update in report.updates
    ]
    return ReportOut(
        id=report.id,
        reporter_alias=f"Petani TT-{report.id:04d}",
        text=report.text,
        incident_description=report.incident_description,
        image_url=report.image_url,
        evidence_urls=report.evidence_urls or [],
        evidence_count=len(report.evidence_urls or []),
        evidence_target=EVIDENCE_TARGET,
        evidence_unavailable=report.evidence_unavailable,
        category=report.category,
        severity=report.severity,
        medical_needed=report.medical_needed,
        needs=report.needs or [],
        ai_summary=report.ai_summary,
        ai_confidence=report.ai_confidence,
        triage_source=report.triage_source,
        review_required=report.review_required,
        readiness_score=report.readiness_score,
        readiness_critique=report.readiness_critique or [],
        farmer_profile=FarmerProfileOut(
            name=report.farmer_profile.name if report.farmer_profile else None,
            is_farmer=report.reporter_is_farmer,
            is_local_farmer=report.reporter_is_local,
            home_location=(
                report.farmer_profile.home_location if report.farmer_profile else None
            ),
            available_for_follow_up=report.follow_up_available,
            privacy_consent_at=(
                report.farmer_profile.privacy_consent_at
                if report.farmer_profile
                else None
            ),
            privacy_consent_version=(
                report.farmer_profile.privacy_consent_version
                if report.farmer_profile
                else None
            ),
            privacy_consent_method=(
                report.farmer_profile.privacy_consent_method
                if report.farmer_profile
                else None
            ),
            profile_summary=(
                report.farmer_profile.profile_summary if report.farmer_profile else ""
            ),
        ),
        intake_status=report.status,
        response_status=report.response_status,
        lat=report.lat,
        lon=report.lon,
        location_shared=report.location_shared,
        location_verification_status=report.location_verification_status,
        village=report.village,
        district=report.district,
        regency=report.regency,
        location_label=report.location_label,
        created_at=report.created_at,
        updates=updates,
    )


def _region_aggregate(
    region: Region, reports: list[Report], distance_km: float | None
) -> dict[str, object]:
    category_counts = Counter(report.category for report in reports)
    urgency_counts = Counter(report.severity for report in reports)
    aggregate_needs: Counter[str] = Counter()
    for report in reports:
        aggregate_needs.update(report.needs or [])
    progress = Counter(report.response_status for report in reports)
    return {
        "id": region.id,
        "name": region.name,
        "lat": region.lat,
        "lon": region.lon,
        "distance_km": distance_km,
        "weather_risk": region.weather_risk,
        "report_risk": region.report_risk,
        "risk_score": region.risk_score,
        "last_summary": region.last_summary,
        "report_count": len(reports),
        "category_counts": dict(category_counts),
        "urgency_counts": dict(urgency_counts),
        "aggregate_needs": dict(aggregate_needs),
        "progress": dict(progress),
    }


def _alert_out(alert: Alert) -> AlertOut:
    statuses = Counter(delivery.status for delivery in alert.deliveries)
    return AlertOut(
        id=alert.id,
        area_name=alert.area_name,
        lat=alert.lat,
        lon=alert.lon,
        radius_km=alert.radius_km,
        message=alert.message,
        source=alert.source,
        delivery_count=len(alert.deliveries),
        delivery_statuses=dict(statuses),
        created_at=alert.created_at,
    )


def _report_matches_urgency(report: Report, urgency: str) -> bool:
    if urgency == "all":
        return True
    if urgency == "medical":
        return report.medical_needed
    severity_rank = SEVERITY_ORDER.get(report.severity, 0)
    if urgency == "critical":
        return severity_rank >= SEVERITY_ORDER["critical"]
    if urgency == "high":
        return severity_rank >= SEVERITY_ORDER["high"]
    if urgency == "medium":
        return severity_rank >= SEVERITY_ORDER["medium"]
    return True
