from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
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
    OrganizationPublicOut,
    OrganizationRegisterIn,
    OrganizationOut,
    OrganizationVerificationIn,
    OrganizationVerificationResult,
    PublicReportTrackingOut,
    PublicReportUpdateOut,
    PublicTrackingOrganizationOut,
    RegionPublicOut,
    RegionResponderOut,
    ReportOut,
    ReportStatusUpdateIn,
    ReportStatusUpdateResult,
    ReportUpdateOut,
)
from app.services.classifier import SEVERITY_ORDER, normalize_needs
from app.services.geocoder import is_generic_location_label
from app.services.notifications import NotificationService
from app.services.resources import ResourceService, km_between
from app.services.triage import EVIDENCE_TARGET


router = APIRouter(prefix="/api")
resources = ResourceService()
notifications = NotificationService()
settings = get_settings()


@router.get("/organizations", response_model=list[OrganizationPublicOut])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return (
        db.query(Organization)
        .filter(Organization.verified.is_(True))
        .order_by(Organization.name)
        .all()
    )


@router.post(
    "/organizations/register", response_model=OrganizationOut, status_code=201
)
def register_organization(
    payload: OrganizationRegisterIn, db: Session = Depends(get_db)
) -> Organization:
    existing = (
        db.query(Organization)
        .filter(Organization.name.ilike(payload.name.strip()))
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Nama pendaftar sudah digunakan")

    required_documents = (
        {"identity"}
        if payload.applicant_kind == "individual"
        else {"legal", "mandate"}
    )
    missing_documents = sorted(
        key
        for key in required_documents
        if not payload.document_links.get(key, "").strip()
    )
    if missing_documents:
        raise HTTPException(
            status_code=422,
            detail=(
                "Berkas wajib belum lengkap: " + ", ".join(missing_documents)
            ),
        )

    organization = Organization(
        name=payload.name.strip(),
        type=payload.type.strip(),
        verified=False,
        applicant_kind=payload.applicant_kind,
        registration_status="pending",
        email=payload.email.strip(),
        phone=payload.phone.strip(),
        address=payload.address.strip(),
        contact_name=payload.contact_name.strip(),
        contact_role=payload.contact_role.strip(),
        logo_url=payload.logo_url.strip(),
        website=payload.website.strip(),
        operational_areas=[
            area.strip() for area in payload.operational_areas if area.strip()
        ],
        document_links={
            key: value.strip()
            for key, value in payload.document_links.items()
            if value.strip()
        },
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/admin/organizations", response_model=list[OrganizationOut])
def list_organization_applications(
    status: str = Query(
        default="pending", pattern="^(all|pending|verified|rejected)$"
    ),
    db: Session = Depends(get_db),
) -> list[Organization]:
    query = db.query(Organization)
    if status != "all":
        query = query.filter(Organization.registration_status == status)
    return query.order_by(Organization.created_at.desc()).all()


@router.post(
    "/admin/organizations/{organization_id}/verification",
    response_model=OrganizationVerificationResult,
)
def verify_organization(
    organization_id: int,
    payload: OrganizationVerificationIn,
    db: Session = Depends(get_db),
) -> OrganizationVerificationResult:
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .one_or_none()
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Pendaftar tidak ditemukan")
    organization.registration_status = payload.status
    organization.verified = payload.status == "verified"
    organization.verification_note = payload.note.strip()
    organization.verified_at = datetime.utcnow() if organization.verified else None
    db.add(organization)
    db.commit()
    return OrganizationVerificationResult(
        organization_id=organization.id,
        status=organization.registration_status,
        verified=organization.verified,
    )


@router.get(
    "/public/reports/{public_token}", response_model=PublicReportTrackingOut
)
def public_report_tracking(
    public_token: str, db: Session = Depends(get_db)
) -> PublicReportTrackingOut:
    report = (
        db.query(Report)
        .options(selectinload(Report.updates).selectinload(ReportUpdate.organization))
        .filter(Report.public_token == public_token)
        .one_or_none()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Laporan tidak ditemukan")
    return _public_tracking_out(report)


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


@router.get("/reports/{report_id}/evidence/{evidence_index}")
def responder_report_evidence(
    report_id: int,
    evidence_index: int,
    db: Session = Depends(get_db),
) -> Response:
    report = db.query(Report).filter(Report.id == report_id).one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _evidence_response(report, evidence_index)


@router.get("/public/reports/{public_token}/evidence/{evidence_index}")
def public_report_evidence(
    public_token: str,
    evidence_index: int,
    db: Session = Depends(get_db),
) -> Response:
    report = (
        db.query(Report)
        .filter(Report.public_token == public_token)
        .one_or_none()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Laporan tidak ditemukan")
    return _evidence_response(report, evidence_index)


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
        documentation_urls=[
            url.strip() for url in payload.documentation_urls if url.strip()
        ],
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
    message += (
        f" Cek perkembangan lengkap: "
        f"{settings.app_public_url.rstrip('/')}/track/{report.public_token}"
    )
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


def _evidence_sources(report: Report) -> list[str]:
    sources = list(report.evidence_urls or [])
    if not sources and report.image_url:
        sources.append(report.image_url)
    return sources


def _is_twilio_media(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname == "api.twilio.com" or hostname.endswith(".twiliocdn.com")


def _evidence_response(report: Report, evidence_index: int) -> Response:
    sources = _evidence_sources(report)
    if evidence_index < 0 or evidence_index >= len(sources):
        raise HTTPException(status_code=404, detail="Bukti tidak ditemukan")
    source = sources[evidence_index]
    if not _is_twilio_media(source):
        return RedirectResponse(source, status_code=307)
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(
            status_code=503,
            detail="Kredensial media Twilio belum dikonfigurasi",
        )

    import httpx

    try:
        media = httpx.get(
            source,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            follow_redirects=True,
            timeout=min(settings.openrouter_timeout_seconds, 15),
        )
        media.raise_for_status()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Media Twilio tidak dapat diambil"
        ) from exc
    content_type = media.headers.get("content-type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Media bukan gambar")
    return Response(
        content=media.content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


def _responder_evidence_urls(report: Report) -> list[str]:
    return [
        f"/api/reports/{report.id}/evidence/{index}"
        for index, _ in enumerate(_evidence_sources(report))
    ]


def _public_evidence_urls(report: Report) -> list[str]:
    return [
        f"/api/public/reports/{report.public_token}/evidence/{index}"
        for index, _ in enumerate(_evidence_sources(report))
    ]


def _report_out(report: Report) -> ReportOut:
    evidence_urls = _responder_evidence_urls(report)
    updates = [
        ReportUpdateOut(
            id=update.id,
            status=update.status,
            note=update.note,
            organization_id=update.updated_by,
            organization_name=update.organization.name,
            organization_logo_url=update.organization.logo_url,
            organization_contact_name=update.organization.contact_name,
            organization_contact_role=update.organization.contact_role,
            organization_phone=update.organization.phone,
            organization_email=update.organization.email,
            documentation_urls=update.documentation_urls or [],
            created_at=update.created_at,
        )
        for update in report.updates
    ]
    return ReportOut(
        id=report.id,
        reporter_alias=f"Petani TT-{report.id:04d}",
        text=report.text,
        incident_description=report.incident_description,
        image_url=evidence_urls[0] if evidence_urls else None,
        evidence_urls=evidence_urls,
        evidence_count=len(evidence_urls),
        evidence_target=EVIDENCE_TARGET,
        evidence_unavailable=report.evidence_unavailable,
        category=report.category,
        severity=report.severity,
        medical_needed=report.medical_needed,
        needs=normalize_needs(report.needs or []),
        field_confidences=report.field_confidences or {},
        field_confidence_reasons=report.field_confidence_reasons or {},
        field_verification=report.field_verification or {},
        evidence_assessments=report.evidence_assessments or [],
        verified_evidence_count=sum(
            1
            for item in (report.evidence_assessments or [])
            if item.get("status") == "verified_visual"
        ),
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


def _public_tracking_organization(
    organization: Organization,
) -> PublicTrackingOrganizationOut:
    show_official_contact = organization.applicant_kind == "organization"
    return PublicTrackingOrganizationOut(
        name=organization.name,
        type=organization.type,
        logo_url=organization.logo_url,
        contact_name=organization.contact_name if show_official_contact else "",
        contact_role=organization.contact_role if show_official_contact else "",
        phone=organization.phone if show_official_contact else "",
        email=organization.email if show_official_contact else "",
        website=organization.website,
    )


def _public_tracking_out(report: Report) -> PublicReportTrackingOut:
    public_updates = [
        PublicReportUpdateOut(
            id=update.id,
            status=update.status,
            note=update.note,
            documentation_urls=update.documentation_urls or [],
            organization=_public_tracking_organization(update.organization),
            created_at=update.created_at,
        )
        for update in report.updates
    ]
    responsible = (
        _public_tracking_organization(report.updates[-1].organization)
        if report.updates
        else None
    )
    public_location_label = report.location_label
    if report.location_shared and is_generic_location_label(public_location_label):
        public_location_label = "Lokasi dibagikan melalui WhatsApp"
    return PublicReportTrackingOut(
        tracking_id=f"TT-{report.id:04d}",
        incident_description=report.incident_description,
        ai_summary=report.ai_summary,
        category=report.category,
        severity=report.severity,
        needs=normalize_needs(report.needs or []),
        response_status=report.response_status,
        village=report.village,
        district=report.district,
        regency=report.regency,
        location_label=public_location_label,
        evidence_urls=_public_evidence_urls(report),
        created_at=report.created_at,
        updated_at=report.updated_at,
        updates=public_updates,
        responsible_organization=responsible,
    )


def _region_aggregate(
    region: Region, reports: list[Report], distance_km: float | None
) -> dict[str, object]:
    category_counts = Counter(report.category for report in reports)
    urgency_counts = Counter(report.severity for report in reports)
    aggregate_needs: Counter[str] = Counter()
    for report in reports:
        aggregate_needs.update(normalize_needs(report.needs or []))
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
