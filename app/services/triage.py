from sqlalchemy.orm import Session

from app.models import Region, Report, ReportStatus
from app.services.classifier import SEVERITY_ORDER, MockClassifier
from app.services.geocoder import MockGeocoder
from app.services.resources import ResourceService, km_between
from app.services.weather import MockWeatherRisk


FOLLOW_UPS = {
    "location": "Lokasinya di desa/kecamatan mana? Kalau bisa share location WhatsApp.",
    "severity": "Seberapa parah? Balas: ringan, sedang, parah, atau darurat.",
    "medical_needed": "Ada kebutuhan medis darurat? Balas: ya/tidak.",
}


class TriageService:
    def __init__(self) -> None:
        self.classifier = MockClassifier()
        self.geocoder = MockGeocoder()
        self.weather = MockWeatherRisk()
        self.resources = ResourceService()

    def ingest(
        self,
        db: Session,
        *,
        sender: str,
        text: str,
        image_url: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        location_label: str | None = None,
    ) -> tuple[Report, str]:
        classification = self.classifier.classify(text, image_url)
        geo = self.geocoder.resolve(text, lat, lon, location_label)

        missing_fields = list(classification.missing_fields)
        if geo and "location" in missing_fields:
            missing_fields.remove("location")

        follow_up = FOLLOW_UPS.get(missing_fields[0]) if missing_fields else None
        status = ReportStatus.needs_follow_up.value if follow_up else ReportStatus.complete.value

        region = None
        if geo:
            region = self._get_or_create_region(db, geo.region_name, geo.lat, geo.lon)

        report = Report(
            sender=sender,
            text=text,
            image_url=image_url,
            category=classification.category,
            severity=classification.severity,
            medical_needed=classification.medical_needed,
            status=status,
            follow_up_question=follow_up,
            lat=geo.lat if geo else None,
            lon=geo.lon if geo else None,
            location_label=geo.label if geo else location_label,
            region=region,
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        if region:
            self.recalculate_region(db, region)

        if follow_up:
            return report, follow_up
        return report, "Terima kasih. Laporan sudah masuk dan sedang diprioritaskan."

    def _get_or_create_region(self, db: Session, name: str, lat: float, lon: float) -> Region:
        region = db.query(Region).filter(Region.name == name).one_or_none()
        if region:
            return region

        weather_risk = self.weather.risk_for_region(name)
        region = Region(name=name, lat=lat, lon=lon, weather_risk=weather_risk, risk_score=weather_risk)
        db.add(region)
        db.commit()
        db.refresh(region)
        return region

    def recalculate_region(self, db: Session, region: Region) -> Region:
        reports = db.query(Report).filter(Report.region_id == region.id).all()
        if not reports:
            region.report_risk = 0.0
            region.risk_score = region.weather_risk
            region.last_summary = "No field reports yet; showing weather baseline only."
        else:
            severity_points = [SEVERITY_ORDER.get(report.severity, 1) for report in reports]
            medical_count = sum(1 for report in reports if report.medical_needed)
            report_risk = min(1.0, (sum(severity_points) / (len(reports) * 4)) + min(0.25, medical_count * 0.08))
            region.report_risk = round(report_risk, 2)
            region.risk_score = round((region.weather_risk * 0.45) + (report_risk * 0.55), 2)
            region.last_summary = self._summary_for_region(db, region, reports, medical_count)

        db.add(region)
        db.commit()
        db.refresh(region)
        return region

    def _summary_for_region(self, db: Session, region: Region, reports: list[Report], medical_count: int) -> str:
        highest = max(reports, key=lambda report: SEVERITY_ORDER.get(report.severity, 0))
        nearest = self.resources.nearest(db, region.lat, region.lon, limit=1)
        nearest_text = "nearest resource not registered"
        if nearest:
            distance = km_between(region.lat, region.lon, nearest[0].lat, nearest[0].lon)
            nearest_text = f"{nearest[0].name} approx {distance:.0f}km away"

        access_note = "road access reportedly cut" if any("putus" in report.text.lower() for report in reports) else "road access unknown"
        return (
            f"{len(reports)} reports, {medical_count} medical-urgent, "
            f"top category {highest.category}/{highest.severity}, {nearest_text}, {access_note}."
        )

