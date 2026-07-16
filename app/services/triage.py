from sqlalchemy.orm import Session

from app.models import ConversationState, InboundMessage, Region, Report, ReportStatus
from app.services.classifier import Classifier, SEVERITY_ORDER, get_classifier
from app.services.geocoder import MockGeocoder
from app.services.resources import ResourceService, km_between
from app.services.weather import MockWeatherRisk


FOLLOW_UPS = {
    "location": "Lokasinya di desa/kecamatan mana? Kalau bisa kirim pin lokasi WhatsApp.",
    "severity": "Seberapa parah kondisinya? Balas: ringan, sedang, parah, atau darurat.",
    "medical_needed": "Ada korban atau kebutuhan medis darurat? Balas: ya atau tidak.",
}
CONSENT_NOTICE = (
    "Dengan melanjutkan, Anda setuju data laporan dan lokasi dipakai untuk koordinasi bantuan. "
    "Nomor telepon tidak ditampilkan ke publik."
)


class TriageService:
    def __init__(
        self,
        classifier: Classifier | None = None,
        geocoder: MockGeocoder | None = None,
        weather: MockWeatherRisk | None = None,
        resources: ResourceService | None = None,
    ) -> None:
        self.classifier = classifier or get_classifier()
        self.geocoder = geocoder or MockGeocoder()
        self.weather = weather or MockWeatherRisk()
        self.resources = resources or ResourceService()

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
        self._record_inbound(db, sender, text, image_url, lat, lon)
        state = (
            db.query(ConversationState)
            .filter(ConversationState.sender == sender)
            .one_or_none()
        )
        if state:
            return self._continue_conversation(
                db,
                state,
                text=text,
                image_url=image_url,
                lat=lat,
                lon=lon,
                location_label=location_label,
            )

        return self._start_report(
            db,
            sender=sender,
            text=text,
            image_url=image_url,
            lat=lat,
            lon=lon,
            location_label=location_label,
        )

    def _record_inbound(
        self,
        db: Session,
        sender: str,
        text: str,
        image_url: str | None,
        lat: float | None,
        lon: float | None,
    ) -> None:
        db.add(
            InboundMessage(
                sender=sender,
                body=text.strip(),
                media_url=image_url,
                lat=lat,
                lon=lon,
            )
        )
        db.commit()

    def _start_report(
        self,
        db: Session,
        *,
        sender: str,
        text: str,
        image_url: str | None,
        lat: float | None,
        lon: float | None,
        location_label: str | None,
    ) -> tuple[Report, str]:
        classification = self.classifier.classify(text, image_url)
        geo = self.geocoder.resolve(text, lat, lon, location_label)

        report = Report(
            sender=sender,
            text=text.strip(),
            image_url=image_url,
            category=classification.category,
            severity=classification.severity,
            medical_needed=classification.medical_needed,
            needs=classification.needs,
            ai_summary=classification.summary,
            ai_confidence=classification.confidence,
            triage_source=classification.source,
            review_required=(
                classification.confidence < 0.65 or classification.category == "unknown"
            ),
            status=ReportStatus.complete.value,
            lat=geo.lat if geo else None,
            lon=geo.lon if geo else None,
            location_label=geo.label if geo else location_label,
        )
        if geo:
            report.region = self._get_or_create_region(
                db, geo.region_name, geo.lat, geo.lon
            )

        pending_fields = self._normalize_pending_fields(
            classification.missing_fields, geo is not None
        )
        follow_up = FOLLOW_UPS.get(pending_fields[0]) if pending_fields else None
        report.status = (
            ReportStatus.needs_follow_up.value if follow_up else ReportStatus.complete.value
        )
        report.follow_up_question = follow_up

        db.add(report)
        db.commit()
        db.refresh(report)

        if report.region:
            self.recalculate_region(db, report.region)

        if pending_fields:
            self._save_state(db, sender, report.id, pending_fields)
            db.commit()

        acknowledgement = (
            f"✅ Laporan TT-{report.id:04d} sudah diterima dan langsung masuk dashboard.\n"
            f"{CONSENT_NOTICE}"
        )
        if follow_up:
            acknowledgement += f"\n\n{follow_up}"
        else:
            acknowledgement += "\n\nTim responder dapat mulai menindaklanjuti laporan Anda."
        return report, acknowledgement

    def _continue_conversation(
        self,
        db: Session,
        state: ConversationState,
        *,
        text: str,
        image_url: str | None,
        lat: float | None,
        lon: float | None,
        location_label: str | None,
    ) -> tuple[Report, str]:
        report = db.query(Report).filter(Report.id == state.report_id).one_or_none()
        if text.strip().lower() in {"batal", "cancel", "abort", "reset"}:
            if report:
                db.delete(report)
            db.delete(state)
            db.commit()
            return (
                report or Report(id=0, status=ReportStatus.complete.value),
                "Laporan dibatalkan. Silakan kirim pesan baru jika ingin melaporkan kejadian lain.",
            )

        if report is None:
            db.delete(state)
            db.commit()
            return self._start_report(
                db,
                sender=state.sender,
                text=text,
                image_url=image_url,
                lat=lat,
                lon=lon,
                location_label=location_label,
            )

        pending_fields = self._pending_fields(state.pending_fields)
        observations = self._extract_observations(text, lat, lon, location_label)
        satisfied_fields: list[str] = []

        report.text = self._append_message(report.text, text)
        if image_url:
            report.image_url = image_url

        if observations["geo"] is not None:
            geo = observations["geo"]
            report.lat = geo.lat
            report.lon = geo.lon
            report.location_label = geo.label
            report.region = self._get_or_create_region(
                db, geo.region_name, geo.lat, geo.lon
            )
            satisfied_fields.append("location")

        if observations["severity"] is not None:
            report.severity = observations["severity"]
            satisfied_fields.append("severity")

        if observations["medical_needed"] is not None:
            report.medical_needed = observations["medical_needed"]
            satisfied_fields.append("medical_needed")

        remaining_fields = [
            field for field in pending_fields if field not in satisfied_fields
        ]
        report.status = (
            ReportStatus.needs_follow_up.value
            if remaining_fields
            else ReportStatus.complete.value
        )
        report.follow_up_question = (
            FOLLOW_UPS.get(remaining_fields[0]) if remaining_fields else None
        )

        db.add(report)
        if remaining_fields:
            self._save_state(db, state.sender, report.id, remaining_fields)
        else:
            db.delete(state)
        db.commit()
        db.refresh(report)

        if report.region:
            self.recalculate_region(db, report.region)

        if remaining_fields:
            current_field = remaining_fields[0]
            prefix = "Saya belum bisa membaca jawaban itu. " if not satisfied_fields else ""
            return report, prefix + FOLLOW_UPS[current_field]
        return (
            report,
            f"✅ Data laporan TT-{report.id:04d} sudah lengkap. Terima kasih; kami akan mengabari setiap perubahan status.",
        )

    def _extract_observations(
        self,
        text: str,
        lat: float | None,
        lon: float | None,
        location_label: str | None,
    ) -> dict[str, object | None]:
        return {
            "geo": self.geocoder.resolve(text, lat, lon, location_label),
            "severity": self._extract_severity(text),
            "medical_needed": self._extract_medical_answer(text),
        }

    def _extract_severity(self, text: str) -> str | None:
        lower = text.lower()
        if any(word in lower for word in ["darurat", "terjebak", "hilang", "evakuasi"]):
            return "critical"
        if any(
            word in lower
            for word in ["parah", "besar", "tinggi", "dada", "arus", "putus", "meninggal"]
        ):
            return "high"
        if any(word in lower for word in ["sedang", "lumayan", "lutut"]):
            return "medium"
        if any(word in lower for word in ["ringan", "sedikit", "surut"]):
            return "low"
        return None

    def _extract_medical_answer(self, text: str) -> bool | None:
        lower = text.lower().strip()
        if not lower:
            return None
        if any(
            phrase in lower
            for phrase in [
                "tidak perlu medis",
                "tidak butuh medis",
                "aman",
                "tidak ada korban",
                "tidak",
                "nggak",
                "gak",
            ]
        ):
            return False
        if any(
            phrase in lower
            for phrase in [
                "ya",
                "iya",
                "perlu",
                "butuh",
                "sakit",
                "luka",
                "medis",
                "dokter",
                "puskesmas",
                "lansia",
                "hamil",
            ]
        ):
            return True
        return None

    def _normalize_pending_fields(
        self, missing_fields: list[str], has_geo: bool
    ) -> list[str]:
        ordered_fields = ["location", "severity", "medical_needed"]
        pending_fields = [field for field in ordered_fields if field in missing_fields]
        if has_geo and "location" in pending_fields:
            pending_fields.remove("location")
        return pending_fields

    def _pending_fields(self, raw_fields: str) -> list[str]:
        return [field for field in raw_fields.split(",") if field]

    def _save_state(
        self, db: Session, sender: str, report_id: int, pending_fields: list[str]
    ) -> None:
        state = (
            db.query(ConversationState)
            .filter(ConversationState.sender == sender)
            .one_or_none()
        )
        if state is None:
            state = ConversationState(
                sender=sender,
                report_id=report_id,
                pending_fields=",".join(pending_fields),
            )
        else:
            state.report_id = report_id
            state.pending_fields = ",".join(pending_fields)
        db.add(state)

    def _append_message(self, existing_text: str, new_text: str) -> str:
        cleaned = new_text.strip()
        if not cleaned:
            return existing_text
        if not existing_text:
            return cleaned
        return f"{existing_text}\n{cleaned}"

    def _get_or_create_region(
        self, db: Session, name: str, lat: float, lon: float
    ) -> Region:
        region = db.query(Region).filter(Region.name == name).one_or_none()
        if region:
            return region

        weather_risk = self.weather.risk_for_region(name)
        region = Region(
            name=name,
            lat=lat,
            lon=lon,
            weather_risk=weather_risk,
            risk_score=weather_risk,
        )
        db.add(region)
        db.commit()
        db.refresh(region)
        return region

    def recalculate_region(self, db: Session, region: Region) -> Region:
        reports = db.query(Report).filter(Report.region_id == region.id).all()
        if not reports:
            region.report_risk = 0.0
            region.risk_score = region.weather_risk
            region.last_summary = "Belum ada laporan lapangan; hanya baseline cuaca."
        else:
            severity_points = [
                SEVERITY_ORDER.get(report.severity, 1) for report in reports
            ]
            medical_count = sum(1 for report in reports if report.medical_needed)
            report_risk = min(
                1.0,
                (sum(severity_points) / (len(reports) * 4))
                + min(0.25, medical_count * 0.08),
            )
            region.report_risk = round(report_risk, 2)
            region.risk_score = round(
                (region.weather_risk * 0.45) + (report_risk * 0.55), 2
            )
            region.last_summary = self._summary_for_region(
                db, region, reports, medical_count
            )

        db.add(region)
        db.commit()
        db.refresh(region)
        return region

    def _summary_for_region(
        self, db: Session, region: Region, reports: list[Report], medical_count: int
    ) -> str:
        highest = max(
            reports, key=lambda report: SEVERITY_ORDER.get(report.severity, 0)
        )
        nearest = self.resources.nearest(db, region.lat, region.lon, limit=1)
        nearest_text = "pos bantuan belum terdaftar"
        if nearest:
            distance = km_between(
                region.lat, region.lon, nearest[0].lat, nearest[0].lon
            )
            nearest_text = f"{nearest[0].name} sekitar {distance:.1f} km"

        access_note = (
            "akses jalan dilaporkan terputus"
            if any("putus" in report.text.lower() for report in reports)
            else "akses jalan belum terkonfirmasi"
        )
        return (
            f"{len(reports)} laporan, {medical_count} butuh medis, urgensi tertinggi "
            f"{highest.category}/{highest.severity}; {nearest_text}; {access_note}."
        )
