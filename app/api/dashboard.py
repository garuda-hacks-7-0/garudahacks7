from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Region, Report
from app.schemas import RegionOut, ReportOut
from app.services.classifier import SEVERITY_ORDER
from app.services.resources import ResourceService, km_between

router = APIRouter(prefix="/api")
resources = ResourceService()


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    urgency: str = Query(default="all", pattern="^(all|medical|critical|high|medium)$"),
    db: Session = Depends(get_db),
) -> list[Report]:
    reports = db.query(Report).order_by(Report.created_at.desc()).limit(100).all()
    return [report for report in reports if _report_matches_urgency(report, urgency)]


@router.get("/regions", response_model=list[RegionOut])
def list_regions(
    urgency: str = Query(default="all", pattern="^(all|medical|critical|high|medium)$"),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    max_distance_km: float = Query(default=13000, ge=0, le=13000),
    db: Session = Depends(get_db),
) -> list[RegionOut]:
    regions = db.query(Region).options(selectinload(Region.reports)).order_by(Region.risk_score.desc()).all()
    output: list[RegionOut] = []
    for region in regions:
        if not _region_matches_urgency(region, urgency):
            continue

        item = RegionOut.model_validate(region)
        if lat is not None and lon is not None:
            item.distance_km = round(km_between(lat, lon, region.lat, region.lon), 1)
            if item.distance_km > max_distance_km:
                continue

        item.nearest_resources = resources.nearest(db, region.lat, region.lon, limit=3)
        output.append(item)
    return output


@router.get("/regions/{region_id}", response_model=RegionOut)
def region_detail(region_id: int, db: Session = Depends(get_db)) -> RegionOut:
    region = db.query(Region).options(selectinload(Region.reports)).filter(Region.id == region_id).one()
    item = RegionOut.model_validate(region)
    item.nearest_resources = resources.nearest(db, region.lat, region.lon, limit=3)
    return item


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


def _region_matches_urgency(region: Region, urgency: str) -> bool:
    if urgency == "all":
        return True
    if any(_report_matches_urgency(report, urgency) for report in region.reports):
        return True
    if urgency == "critical":
        return region.risk_score >= 0.85
    if urgency == "high":
        return region.risk_score >= 0.75
    if urgency == "medium":
        return region.risk_score >= 0.55
    return False
