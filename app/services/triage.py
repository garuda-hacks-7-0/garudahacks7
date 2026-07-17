from datetime import datetime
import json
import re

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ConversationState,
    FarmerProfile,
    InboundMessage,
    Region,
    Report,
    ReportStatus,
    ResponseStatus,
)
from app.services.classifier import (
    Classification,
    Classifier,
    SEVERITY_ORDER,
    get_classifier,
    normalize_needs,
)
from app.services.geocoder import GeoResult, MockGeocoder
from app.services.resources import ResourceService, km_between
from app.services.weather import MockWeatherRisk


EVIDENCE_TARGET = 1
READINESS_THRESHOLD = 70
FIELD_CONFIDENCE_THRESHOLD = 0.7
GREETINGS = {"hi", "hai", "halo", "hello", "hey", "pagi", "siang", "sore", "malam"}
START_COMMANDS = {
    "lapor",
    "lapot",
    "lpor",
    "laopr",
    "mulai",
    "buat laporan",
    "laporan baru",
}
FOLLOW_UP_ORDER = [
    "evidence",
    "village",
    "district",
    "regency",
    "location_verification",
    "description",
    "is_local_farmer",
    "needs",
]
FOLLOW_UPS = {
    "evidence": "Silakan upload foto lokasi yang menunjukkan bukti terdampak.",
    "village": (
        "Kirim lokasi terdampak lewat WhatsApp: tekan 📎 > Location > "
        "Send your current location (bukan Live Location). Jika tidak ingin "
        "share location, ketik nama Desa/Kelurahannya."
    ),
    "district": "Apa nama Kecamatan lokasi terdampak?",
    "regency": "Apa nama Kota/Kabupaten lokasi terdampak?",
    "location_verification": (
        "Lokasinya belum ditemukan di peta. Periksa kembali penulisan Desa/Kelurahan, "
        "Kecamatan, dan Kota/Kabupaten; tambahkan patokan terdekat; atau kirim "
        "Share Location WhatsApp (bukan Live Location)."
    ),
    "description": (
        "Ceritakan dampak bencananya. Contoh: banjir merendam sawah dan "
        "merusak tanaman padi sejak pagi."
    ),
    "is_local_farmer": (
        "Apakah Anda petani atau penggarap yang bertani di daerah terdampak tersebut? "
        "Balas YA atau TIDAK."
    ),
    "needs": (
        "Saya belum yakin bantuan yang paling dibutuhkan. Apakah kebutuhannya berupa "
        "evakuasi, medis, pangan, air bersih, pengungsian, pompa, benih, alat pertanian, "
        "atau lainnya? Jika belum tahu, balas BELUM TAHU."
    ),
}
CONSENT_NOTICE = (
    "Nomor WhatsApp-mu tetap dirahasiakan."
)
REPORT_FORM_TEMPLATE = (
    "*FORM LAPORAN PETANI*\n"
    "Desa/Kelurahan: Sayung\n"
    "Kecamatan: Sayung\n"
    "Kota/Kabupaten: Demak\n"
    "Deskripsi dampak: Banjir merendam sawah dan merusak tanaman padi sejak pagi.\n"
    "Bantuan yang dibutuhkan: Pangan, air bersih, pompa\n"
    "Petani/penggarap di lokasi: YA/TIDAK"
)
FORM_ONLY_MESSAGE = (
    "*FORM LAPORAN PETANI*\n"
    "Desa/Kelurahan: \n"
    "Kecamatan: \n"
    "Kota/Kabupaten: \n"
    "Deskripsi dampak: \n"
    "Bantuan yang dibutuhkan: \n"
    "Petani/penggarap di lokasi: YA/TIDAK"
)
FORM_REQUIRED_MESSAGE = (
    "Mohon gunakan form agar laporan bisa diproses dengan cepat. Copy-paste, "
    "ganti contoh jawabannya, lalu kirim dalam satu pesan:\n\n"
    f"{REPORT_FORM_TEMPLATE}\n\n"
    "Jika memakai Share Location, hapus tiga baris lokasi manual lalu kirim "
    "Share Location WhatsApp secara terpisah (bukan Live Location).\n\n"
    "Foto bukti juga boleh dikirim terpisah.\n\n"
    "Jenis bantuan boleh lebih dari satu. Tulis BELUM TAHU jika belum dapat "
    "menentukannya.\n\n"
    "Ketik SALIN FORM jika ingin menerima form kosong dalam satu pesan.\n\n"
    "Ketik BATAL untuk membatalkan laporan."
)
LOCATION_CHECK_MESSAGE = "Sebentar ya, aku cek dulu lokasi kamu… 📍"
WELCOME_MESSAGE = (
    "Halo, terima kasih sudah menghubungi PetaNih! 🌾\n\n"
    "Untuk membuat laporan, upload minimal satu foto daerah terdampak lalu kirim "
    "data menggunakan form berikut dalam satu pesan.\n\n"
    f"{REPORT_FORM_TEMPLATE}\n\n"
    "Lokasi boleh diganti dengan Share Location: tekan 📎 > Location > "
    "Send your current location (bukan Live Location), lalu hapus tiga baris "
    "lokasi manual dari form.\n\n"
    "Foto dan Share Location boleh dikirim terpisah, tetapi data teks wajib "
    "menggunakan form.\n\n"
    "Jenis bantuan boleh lebih dari satu. Tulis BELUM TAHU jika belum dapat "
    "menentukannya.\n\n"
    "Ketik SALIN FORM jika ingin menerima form kosong dalam satu pesan."
)
CANCEL_FOOTER = "Ketik BATAL untuk membatalkan laporan."
PRIVACY_CONSENT_VERSION = "2026-07-17-v1"
PRIVACY_CONSENT_PROMPT = (
    "Halo, terima kasih sudah menghubungi PetaNih! 🌾\n\n"
    "Sebelum lanjut, PetaNih perlu menyimpan nomor WhatsApp, foto, lokasi, dan "
    "isi laporan untuk verifikasi serta pembaruan status. Data tidak ditampilkan "
    "kepada publik dan kamu dapat meminta penghapusan data.\n\n"
    "Pilih *SETUJU* untuk melanjutkan atau *BATAL* untuk membatalkan."
)
PRIVACY_CONSENT_DECLINED = (
    "Baik, PetaNih tidak akan memproses laporanmu. Kamu bisa menghubungi kami lagi "
    "kapan saja jika berubah pikiran."
)
PRIVACY_CONSENT_ACCEPTED = (
    "Terima kasih, persetujuanmu sudah dicatat. ✅\n\n" + WELCOME_MESSAGE
)
READINESS_WEIGHTS = {
    "evidence": 25,
    "village": 10,
    "district": 10,
    "regency": 10,
    "description": 20,
    "is_local_farmer": 15,
    "needs": 10,
}
CRITIQUE_MESSAGES = {
    "evidence": "foto bukti terdampak belum diunggah",
    "village": "Desa/Kelurahan lokasi belum diketahui",
    "district": "Kecamatan lokasi belum diketahui",
    "regency": "Kota/Kabupaten lokasi belum diketahui",
    "location_verification": "lokasi manual belum berhasil diverifikasi di peta",
    "description": "deskripsi kejadian dan dampak belum cukup spesifik",
    "is_local_farmer": "status pelapor sebagai petani/penggarap daerah tersebut belum dikonfirmasi",
    "needs": "jenis bantuan yang dibutuhkan belum cukup jelas",
}


class TriageService:
    def __init__(
        self,
        classifier: Classifier | None = None,
        geocoder: MockGeocoder | None = None,
        weather: MockWeatherRisk | None = None,
        resources: ResourceService | None = None,
        privacy_consent_required: bool = True,
        form_required: bool = False,
    ) -> None:
        self.classifier = classifier or get_classifier()
        self.geocoder = geocoder or MockGeocoder()
        self.weather = weather or MockWeatherRisk()
        self.resources = resources or ResourceService()
        self.privacy_consent_required = privacy_consent_required
        self.form_required = form_required
        self.public_url = get_settings().app_public_url.rstrip("/")

    def ingest(
        self,
        db: Session,
        *,
        sender: str,
        text: str,
        image_url: str | None = None,
        image_urls: list[str] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        location_label: str | None = None,
        button_payload: str | None = None,
    ) -> tuple[Report | None, str]:
        evidence_urls = self._normalize_evidence_urls(image_url, image_urls)
        if self.privacy_consent_required:
            consent_reply = self._privacy_consent_reply(
                db,
                sender=sender,
                text=text,
                button_payload=button_payload,
                image_url=evidence_urls[0] if evidence_urls else None,
                lat=lat,
                lon=lon,
            )
            if consent_reply is not None:
                return None, consent_reply
        self._record_inbound(
            db,
            sender,
            text,
            evidence_urls[0] if evidence_urls else None,
            lat,
            lon,
            button_payload,
        )
        state = (
            db.query(ConversationState)
            .filter(ConversationState.sender == sender)
            .one_or_none()
        )
        active_report = None
        if state is not None:
            active_report = (
                db.query(Report).filter(Report.id == state.report_id).one_or_none()
            )
            if active_report is not None:
                current_pending = ",".join(self._missing_fields(active_report))
                if state.pending_fields != current_pending:
                    state.pending_fields = current_pending
                    db.add(state)
                    db.commit()

        if self._is_form_copy_command(text, button_payload):
            return active_report, FORM_ONLY_MESSAGE

        if self.form_required:
            has_attachment = bool(evidence_urls) or (
                lat is not None and lon is not None
            )
            if self._is_cancel_command(text):
                if state is not None:
                    if active_report is not None:
                        db.delete(active_report)
                    db.delete(state)
                    db.commit()
                    return (
                        active_report,
                        "Oke, draft dibatalkan. Ketik *LAPOR* kalau mau mulai lagi.",
                    )
                return None, "Belum ada draft aktif. Ketik *LAPOR* untuk mulai."
            if (
                not has_attachment
                and (self._is_greeting(text) or self._is_start_command(text))
            ):
                if active_report is not None:
                    return (
                        active_report,
                        f"Halo 👋 Draft *TT-{active_report.id:04d}* masih ada.\n\n"
                        f"{FORM_REQUIRED_MESSAGE}",
                    )
                return None, WELCOME_MESSAGE
            active_form_follow_up = bool(
                state is not None
                and active_report is not None
                and self.is_report_form(active_report.text or "")
            )
            if (
                text.strip()
                and not self.is_report_form(text)
                and not active_form_follow_up
            ):
                if not has_attachment:
                    return active_report, FORM_REQUIRED_MESSAGE
                blank_classification = self._blank_form_classification()
                if state is not None:
                    attached_report, attached_reply = self._continue_conversation(
                        db,
                        state,
                        text="",
                        evidence_urls=evidence_urls,
                        lat=lat,
                        lon=lon,
                        location_label=location_label,
                        classification=blank_classification,
                    )
                else:
                    attached_report, attached_reply = self._start_report(
                        db,
                        sender=sender,
                        text="",
                        evidence_urls=evidence_urls,
                        lat=lat,
                        lon=lon,
                        location_label=location_label,
                        classification=blank_classification,
                    )
                if attached_report.readiness_score >= READINESS_THRESHOLD:
                    return attached_report, attached_reply
                return attached_report, FORM_REQUIRED_MESSAGE

        classification_image = evidence_urls[0] if evidence_urls else None
        if (
            classification_image is None
            and active_report is not None
            and active_report.image_url
            and self.is_report_form(text)
        ):
            classification_image = active_report.image_url
        classification = self.classifier.classify(
            self._classification_context(db, state, text),
            classification_image,
        )
        if state is not None and self._is_greeting(text) and not evidence_urls:
            active_report = (
                db.query(Report).filter(Report.id == state.report_id).one_or_none()
            )
            if (
                active_report is not None
                and not active_report.incident_description
                and self._is_greeting(active_report.text)
            ):
                db.delete(state)
                db.delete(active_report)
                db.commit()
                return None, WELCOME_MESSAGE
            if active_report is not None:
                pending_fields = self._pending_fields(state.pending_fields)
                active_field = pending_fields[0] if pending_fields else None
                question = (
                    FOLLOW_UPS.get(active_field, active_report.follow_up_question)
                    or "Ketik *BATAL* untuk membatalkan laporan ini."
                )
                return (
                    active_report,
                    f"Halo 👋 Draft *TT-{active_report.id:04d}* masih ada.\n\n"
                    f"{question}\n\n{CANCEL_FOOTER}",
                )
        if (
            state is None
            and not evidence_urls
            and lat is None
            and lon is None
            and self._is_greeting(text)
        ):
            return None, WELCOME_MESSAGE
        if state:
            return self._continue_conversation(
                db,
                state,
                text=text,
                evidence_urls=evidence_urls,
                lat=lat,
                lon=lon,
                location_label=location_label,
                classification=classification,
            )

        return self._start_report(
            db,
            sender=sender,
            text=text,
            evidence_urls=evidence_urls,
            lat=lat,
            lon=lon,
            location_label=location_label,
            classification=classification,
        )

    def _record_inbound(
        self,
        db: Session,
        sender: str,
        text: str,
        image_url: str | None,
        lat: float | None,
        lon: float | None,
        button_payload: str | None,
    ) -> None:
        db.add(
            InboundMessage(
                sender=sender,
                body=text.strip(),
                media_url=image_url,
                button_payload=button_payload,
                lat=lat,
                lon=lon,
            )
        )
        db.commit()

    def _privacy_consent_reply(
        self,
        db: Session,
        *,
        sender: str,
        text: str,
        button_payload: str | None,
        image_url: str | None,
        lat: float | None,
        lon: float | None,
    ) -> str | None:
        profile = (
            db.query(FarmerProfile)
            .filter(FarmerProfile.sender == sender)
            .one_or_none()
        )
        action = self._privacy_consent_action(text, button_payload)
        if action == "accept":
            if profile is None:
                profile = FarmerProfile(sender=sender)
            profile.privacy_consent_at = datetime.utcnow()
            profile.privacy_consent_version = PRIVACY_CONSENT_VERSION
            profile.privacy_consent_method = (
                "whatsapp_button" if button_payload else "whatsapp_text"
            )
            db.add(profile)
            db.commit()
            self._record_inbound(
                db,
                sender,
                text,
                image_url,
                lat,
                lon,
                button_payload,
            )
            return PRIVACY_CONSENT_ACCEPTED

        has_current_consent = bool(
            profile
            and profile.privacy_consent_at
            and profile.privacy_consent_version == PRIVACY_CONSENT_VERSION
        )
        if has_current_consent:
            return None
        if action == "cancel":
            return PRIVACY_CONSENT_DECLINED
        return PRIVACY_CONSENT_PROMPT

    def _privacy_consent_action(
        self, text: str, button_payload: str | None
    ) -> str | None:
        payload = (button_payload or "").strip().upper()
        if payload == "CONSENT_ACCEPT":
            return "accept"
        if payload == "CONSENT_CANCEL":
            return "cancel"
        command = self._normalized_command(text)
        if command in {"setuju", "saya setuju", "consent accept"}:
            return "accept"
        if command in {"batal", "tidak setuju", "consent cancel"}:
            return "cancel"
        return None

    def has_current_privacy_consent(self, db: Session, sender: str) -> bool:
        profile = (
            db.query(FarmerProfile)
            .filter(FarmerProfile.sender == sender)
            .one_or_none()
        )
        return bool(
            profile
            and profile.privacy_consent_at
            and profile.privacy_consent_version == PRIVACY_CONSENT_VERSION
        )

    def is_report_form(self, text: str) -> bool:
        lower = text.lower()
        return bool(
            re.search(r"\bform\s+laporan(?:\s+petani)?\b", lower)
            and re.search(r"\bdeskripsi\s+dampak\s*:", lower)
            and re.search(r"\bbantuan\s+yang\s+dibutuhkan\s*:", lower)
            and re.search(r"\bpetani(?:/penggarap)?\s+di\s+lokasi\s*:", lower)
        )

    def _blank_form_classification(self) -> Classification:
        return Classification(
            category="unknown",
            severity="unknown",
            medical_needed=False,
            missing_fields=["severity", "medical_needed"],
            needs=[],
            summary="",
            confidence=0.0,
            source="form_attachment",
        )

    def _start_report(
        self,
        db: Session,
        *,
        sender: str,
        text: str,
        evidence_urls: list[str],
        lat: float | None,
        lon: float | None,
        location_label: str | None,
        classification: Classification,
    ) -> tuple[Report, str]:
        primary_image = evidence_urls[0] if evidence_urls else None
        geo = self.geocoder.resolve(text, lat, lon, location_label)
        profile = self._get_or_create_profile(db, sender)
        self._apply_classification_to_profile(profile, classification)

        severity_confirmed = "severity" not in classification.missing_fields
        medical_confirmed = "medical_needed" not in classification.missing_fields
        incident_description = self._extract_description(
            text, classification, expected=False
        )
        report_location = geo.label if geo else location_label
        reporter_is_local = classification.is_local_farmer

        report = Report(
            sender=sender,
            text=text.strip(),
            incident_description=incident_description or "",
            image_url=primary_image,
            evidence_urls=evidence_urls,
            evidence_unavailable=False,
            category=classification.category,
            severity=classification.severity if severity_confirmed else "unknown",
            severity_confirmed=severity_confirmed,
            medical_needed=classification.medical_needed,
            medical_status_confirmed=medical_confirmed,
            reporter_is_farmer=(
                classification.is_farmer
                if classification.is_farmer is not None
                else profile.is_farmer
            ),
            reporter_is_local=reporter_is_local,
            follow_up_available=(
                classification.available_for_follow_up
                if classification.available_for_follow_up is not None
                else profile.available_for_follow_up
            ),
            needs=normalize_needs(classification.needs),
            field_confidences=dict(classification.field_confidences),
            field_confidence_reasons=dict(classification.field_confidence_reasons),
            field_verification={},
            evidence_assessments=[],
            follow_up_counts={},
            ai_summary=classification.summary,
            ai_confidence=classification.confidence,
            triage_source=classification.source,
            farmer_profile=profile,
            lat=geo.lat if geo else None,
            lon=geo.lon if geo else None,
            location_shared=lat is not None and lon is not None,
            village=classification.village or "",
            district=classification.district or "",
            regency=classification.regency or "",
            location_label=report_location,
        )
        self._apply_shared_location_details(report, geo)
        self._sync_location_label(report)
        self._update_location_verification(report, geo_found=geo is not None)
        if primary_image:
            self._apply_image_assessment(report, primary_image, classification)
        self._refresh_field_metadata(report)
        db.add_all([profile, report])
        if geo:
            report.region = self._get_or_create_region(
                db, geo.region_name, geo.lat, geo.lon
            )
        self._sync_profile_from_report(profile, report)
        self._refresh_readiness(report)

        db.commit()
        db.refresh(report)

        if report.region:
            self.recalculate_region(db, report.region)

        pending_fields = self._missing_fields(report)
        if pending_fields:
            self._save_state(db, sender, report.id, pending_fields)
            db.commit()

        if self._is_start_command(text):
            opening = f"Siap, laporan TT-{report.id:04d} mulai dibuat."
        else:
            opening = f"✅ Laporan TT-{report.id:04d} diterima."
        acknowledgement = (
            f"{opening} {CONSENT_NOTICE}\n\n"
            f"{self._tracking_message(report)}\n\n"
            f"{self._readiness_message(report)}"
        )
        return report, acknowledgement

    def _continue_conversation(
        self,
        db: Session,
        state: ConversationState,
        *,
        text: str,
        evidence_urls: list[str],
        lat: float | None,
        lon: float | None,
        location_label: str | None,
        classification: Classification,
    ) -> tuple[Report, str]:
        report = db.query(Report).filter(Report.id == state.report_id).one_or_none()
        if text.strip().lower() in {"batal", "cancel", "abort", "reset"}:
            if report:
                db.delete(report)
            db.delete(state)
            db.commit()
            return (
                report or Report(id=0, status=ReportStatus.complete.value),
                "Oke, draft dibatalkan. Ketik *LAPOR* kalau mau mulai lagi.",
            )

        if report is None:
            db.delete(state)
            db.commit()
            return self._start_report(
                db,
                sender=state.sender,
                text=text,
                evidence_urls=evidence_urls,
                lat=lat,
                lon=lon,
                location_label=location_label,
                classification=classification,
            )

        if self._is_start_command(text):
            return (
                report,
                f"Kita lanjutkan *TT-{report.id:04d}* ya.\n\n"
                f"{self._readiness_message(report)}",
            )

        profile = report.farmer_profile or self._get_or_create_profile(db, state.sender)
        report.farmer_profile = profile
        current_fields = self._pending_fields(state.pending_fields)
        current_field = current_fields[0] if current_fields else None
        recognized_fields: set[str] = set()

        report.text = self._append_message(report.text, text)
        self._apply_classification_to_report(report, classification)
        self._apply_classification_to_profile(profile, classification)
        previous_evidence_count = len(report.evidence_urls or [])
        report.evidence_urls = self._merge_evidence_urls(
            report.evidence_urls or [], evidence_urls
        )
        if report.evidence_urls:
            report.image_url = report.evidence_urls[0]
            report.evidence_unavailable = False
        if len(report.evidence_urls) > previous_evidence_count:
            recognized_fields.add("evidence")
        assessed_image = evidence_urls[0] if evidence_urls else report.image_url
        if assessed_image and (
            classification.image_relevant is not None
            or classification.image_reason is not None
        ):
            self._apply_image_assessment(report, assessed_image, classification)

        description = self._extract_description_from_reply(
            text, expected=current_field == "description"
        )
        if description:
            report.incident_description = description
            if current_field == "description":
                self._set_field_confidence(report, "description", 0.95, None)
            elif "description" not in (report.field_confidences or {}):
                self._set_field_confidence(report, "description", 0.9, None)
            recognized_fields.add("description")

        if current_field == "needs":
            follow_up_counts = dict(report.follow_up_counts or {})
            follow_up_counts["needs"] = follow_up_counts.get("needs", 0) + 1
            report.follow_up_counts = follow_up_counts
            direct_needs = normalize_needs([text])
            if direct_needs:
                report.needs = direct_needs
                self._set_field_confidence(report, "needs", 0.95, None)
            else:
                report.needs = []
                self._set_field_confidence(
                    report,
                    "needs",
                    0.0,
                    "Pelapor belum mengetahui bantuan yang paling dibutuhkan.",
                )
            recognized_fields.add("needs")

        for field in ("village", "district", "regency"):
            value = getattr(classification, field)
            if not value and current_field == field:
                value = self._extract_admin_reply(text)
            if value:
                setattr(report, field, value.strip()[:160])
                if current_field == field:
                    self._set_field_confidence(report, field, 0.98, None)
                elif field not in (report.field_confidences or {}):
                    self._set_field_confidence(report, field, 0.9, None)
                recognized_fields.add(field)
        self._sync_location_label(report)

        ai_profile_values = {
            "is_farmer": classification.is_farmer,
            "is_local_farmer": classification.is_local_farmer,
            "follow_up_available": classification.available_for_follow_up,
        }
        if ai_profile_values["is_farmer"] is not None:
            previous = report.reporter_is_farmer
            report.reporter_is_farmer = ai_profile_values["is_farmer"]
            if previous != report.reporter_is_farmer or current_field == "is_farmer":
                recognized_fields.add("is_farmer")
        if ai_profile_values["is_local_farmer"] is not None:
            previous = report.reporter_is_local
            report.reporter_is_local = ai_profile_values["is_local_farmer"]
            if previous != report.reporter_is_local or current_field == "is_local_farmer":
                recognized_fields.add("is_local_farmer")
        if ai_profile_values["follow_up_available"] is not None:
            previous = report.follow_up_available
            report.follow_up_available = ai_profile_values["follow_up_available"]
            if (
                previous != report.follow_up_available
                or current_field == "follow_up_available"
            ):
                recognized_fields.add("follow_up_available")

        should_geocode = (
            current_field
            in {"village", "district", "regency", "location_verification"}
            or lat is not None
            or lon is not None
            or bool(location_label)
            or bool({"village", "district", "regency"}.intersection(recognized_fields))
        )
        geo = (
            self.geocoder.resolve(
                (
                    text
                    if current_field == "location_verification" and text.strip()
                    else self._admin_location_label(report) or text
                ),
                lat,
                lon,
                location_label,
            )
            if should_geocode
            else None
        )
        if geo is not None:
            report.lat = geo.lat
            report.lon = geo.lon
            report.region = self._get_or_create_region(
                db, geo.region_name, geo.lat, geo.lon
            )
            if lat is not None and lon is not None:
                report.location_shared = True
                report.location_label = geo.label
                recognized_fields.add("location")
        self._apply_shared_location_details(report, geo)
        if current_field == "location_verification" and (text.strip() or geo):
            recognized_fields.add("location_attempt")
        if should_geocode:
            self._update_location_verification(report, geo_found=geo is not None)
        self._sync_location_label(report)

        severity = self._extract_severity(text)
        if severity is not None:
            report.severity = severity
            report.severity_confirmed = True
            recognized_fields.add("severity")

        medical_answer = self._extract_medical_answer(
            text, allow_bare=current_field == "medical_needed"
        )
        if medical_answer is not None:
            report.medical_needed = medical_answer
            report.medical_status_confirmed = True
            recognized_fields.add("medical_needed")

        profile_updates = {
            "is_farmer": self._extract_profile_boolean(
                text, "is_farmer", allow_bare=current_field == "is_farmer"
            ),
            "is_local_farmer": self._extract_profile_boolean(
                text,
                "is_local_farmer",
                allow_bare=current_field == "is_local_farmer",
            ),
            "follow_up_available": self._extract_profile_boolean(
                text,
                "follow_up_available",
                allow_bare=current_field == "follow_up_available",
            ),
        }
        if profile_updates["is_farmer"] is not None:
            report.reporter_is_farmer = profile_updates["is_farmer"]
            profile.is_farmer = profile_updates["is_farmer"]
            recognized_fields.add("is_farmer")
        if profile_updates["is_local_farmer"] is not None:
            report.reporter_is_local = profile_updates["is_local_farmer"]
            profile.is_local_farmer = profile_updates["is_local_farmer"]
            self._set_field_confidence(report, "is_local_farmer", 0.99, None)
            recognized_fields.add("is_local_farmer")
        if profile_updates["follow_up_available"] is not None:
            report.follow_up_available = profile_updates["follow_up_available"]
            profile.available_for_follow_up = profile_updates["follow_up_available"]
            recognized_fields.add("follow_up_available")

        self._refresh_field_metadata(report)
        self._sync_profile_from_report(profile, report)
        self._refresh_readiness(report)
        remaining_fields = self._missing_fields(report)

        db.add_all([profile, report])
        if remaining_fields:
            self._save_state(db, state.sender, report.id, remaining_fields)
        else:
            db.delete(state)
        db.commit()
        db.refresh(report)

        if report.region:
            self.recalculate_region(db, report.region)

        prefix = ""
        if self._declines_evidence(text) and "evidence" in remaining_fields:
            prefix = "Foto bukti wajib agar laporan dapat diteruskan.\n\n"
        if not recognized_fields and remaining_fields:
            prefix = prefix or "Maaf, saya belum menangkap jawabannya.\n\n"
        if remaining_fields:
            return report, prefix + self._readiness_message(report)
        return (
            report,
            f"✅ Data TT-{report.id:04d} sudah cukup dan siap ditindaklanjuti. "
            "Kami akan mengabari setiap perubahan status.\n\n"
            f"{self._tracking_message(report)}",
        )

    def _apply_classification_to_report(
        self, report: Report, classification: Classification
    ) -> None:
        if classification.category != "unknown" or report.category == "unknown":
            report.category = classification.category
        if classification.needs:
            report.needs = normalize_needs(classification.needs)
        if classification.summary:
            report.ai_summary = classification.summary
        report.ai_confidence = classification.confidence
        report.triage_source = classification.source
        report.field_confidences = {
            **(report.field_confidences or {}),
            **classification.field_confidences,
        }
        confidence_reasons = dict(report.field_confidence_reasons or {})
        for field, confidence in classification.field_confidences.items():
            if (
                confidence >= FIELD_CONFIDENCE_THRESHOLD
                and field not in classification.field_confidence_reasons
            ):
                confidence_reasons.pop(field, None)
        confidence_reasons.update(classification.field_confidence_reasons)
        report.field_confidence_reasons = confidence_reasons
        if classification.village:
            report.village = classification.village
        if classification.district:
            report.district = classification.district
        if classification.regency:
            report.regency = classification.regency
        if "severity" not in classification.missing_fields:
            report.severity = classification.severity
            report.severity_confirmed = True
        if "medical_needed" not in classification.missing_fields:
            report.medical_needed = classification.medical_needed
            report.medical_status_confirmed = True

    def _classification_context(
        self, db: Session, state: ConversationState | None, latest_text: str
    ) -> str:
        if state is None:
            return latest_text
        report = db.query(Report).filter(Report.id == state.report_id).one_or_none()
        if report is None:
            return latest_text
        pending_fields = self._pending_fields(state.pending_fields)
        active_field = pending_fields[0] if pending_fields else "none"
        internal_confidence = json.dumps(
            {
                "values": report.field_confidences or {},
                "reasons": report.field_confidence_reasons or {},
                "verification": report.field_verification or {},
            },
            ensure_ascii=False,
        )
        return (
            "[RIWAYAT_LAPORAN]\n"
            f"{report.text}\n"
            "[CONFIDENCE_INTERNAL]\n"
            f"{internal_confidence}\n"
            "[FIELD_AKTIF]\n"
            f"{active_field}\n"
            "[JAWABAN_TERBARU]\n"
            f"{latest_text}"
        )

    def _get_or_create_profile(self, db: Session, sender: str) -> FarmerProfile:
        profile = (
            db.query(FarmerProfile).filter(FarmerProfile.sender == sender).one_or_none()
        )
        if profile is None:
            profile = FarmerProfile(sender=sender)
            db.add(profile)
        return profile

    def _apply_classification_to_profile(
        self, profile: FarmerProfile, classification: Classification
    ) -> None:
        if classification.reporter_name:
            profile.name = classification.reporter_name
        if classification.is_farmer is not None:
            profile.is_farmer = classification.is_farmer
        if classification.is_local_farmer is not None:
            profile.is_local_farmer = classification.is_local_farmer
        if classification.home_location:
            profile.home_location = classification.home_location
        if classification.available_for_follow_up is not None:
            profile.available_for_follow_up = classification.available_for_follow_up

    def _sync_profile_from_report(
        self, profile: FarmerProfile, report: Report
    ) -> None:
        if report.reporter_is_farmer is not None:
            profile.is_farmer = report.reporter_is_farmer
        if report.reporter_is_local is not None:
            profile.is_local_farmer = report.reporter_is_local
        if report.follow_up_available is not None:
            profile.available_for_follow_up = report.follow_up_available
        if report.reporter_is_local and report.location_label:
            profile.home_location = report.location_label
        profile.profile_summary = self._profile_summary(profile)

    def _profile_summary(self, profile: FarmerProfile) -> str:
        facts: list[str] = []
        if profile.is_farmer is not None:
            facts.append("petani/penggarap" if profile.is_farmer else "bukan petani/penggarap")
        if profile.is_local_farmer is not None:
            facts.append("petani setempat" if profile.is_local_farmer else "bukan petani setempat")
        if profile.available_for_follow_up is not None:
            facts.append(
                "bersedia dihubungi" if profile.available_for_follow_up else "tidak bersedia dihubungi"
            )
        if profile.home_location:
            facts.append(f"wilayah {profile.home_location}")
        return "; ".join(facts)

    def _set_field_confidence(
        self,
        report: Report,
        field: str,
        confidence: float,
        reason: str | None,
    ) -> None:
        confidences = dict(report.field_confidences or {})
        confidences[field] = round(max(0.0, min(1.0, confidence)), 3)
        report.field_confidences = confidences
        reasons = dict(report.field_confidence_reasons or {})
        if reason:
            reasons[field] = reason[:240]
        else:
            reasons.pop(field, None)
        report.field_confidence_reasons = reasons

    def _apply_image_assessment(
        self,
        report: Report,
        image_url: str,
        classification: Classification,
    ) -> None:
        visual_notes = " ".join(
            value.lower()
            for value in [
                classification.image_findings or "",
                classification.image_reason or "",
            ]
        )
        limited_visual_source = any(
            marker in visual_notes
            for marker in [
                "satelit",
                "satellite",
                "aerial",
                "drone",
                "foto udara",
                "screenshot",
                "tangkapan layar",
                "foto layar",
                "foto stok",
                "stock photo",
                "foto ulang",
            ]
        )
        if classification.image_relevant is False:
            status = "rejected_irrelevant"
        elif classification.image_relevant is True and limited_visual_source:
            status = "supporting_only"
        elif classification.image_matches_report is False:
            status = "rejected_mismatch"
        elif (
            classification.image_relevant is True
            and classification.image_matches_report is True
            and classification.image_confidence >= FIELD_CONFIDENCE_THRESHOLD
        ):
            status = "verified_visual"
        elif (
            classification.image_relevant is True
            and classification.image_matches_report is None
        ):
            status = "needs_comparison"
        else:
            status = "unverified"

        assessment = {
            "url": image_url,
            "status": status,
            "relevant": classification.image_relevant,
            "matches_report": classification.image_matches_report,
            "confidence": round(classification.image_confidence, 3),
            "findings": classification.image_findings or "",
            "reason": classification.image_reason or "",
        }
        assessments = [
            item
            for item in (report.evidence_assessments or [])
            if item.get("url") != image_url
        ]
        assessments.append(assessment)
        report.evidence_assessments = assessments

    def _verified_evidence_count(self, report: Report) -> int:
        return sum(
            1
            for item in (report.evidence_assessments or [])
            if item.get("status") == "verified_visual"
        )

    def _evidence_confidence(self, report: Report) -> float:
        verified = [
            float(item.get("confidence") or 0.0)
            for item in (report.evidence_assessments or [])
            if item.get("status") == "verified_visual"
        ]
        if verified:
            confidence = max(verified)
            if len(verified) == 1:
                confidence = min(confidence, 0.75)
            return confidence
        if not self.form_required and report.evidence_urls:
            return 1.0
        return 0.0

    def _field_confidence(self, report: Report, field: str) -> float:
        value = (report.field_confidences or {}).get(field)
        if value is not None:
            return max(0.0, min(1.0, float(value)))
        legacy_present = {
            "village": bool(report.village.strip()),
            "district": bool(report.district.strip()),
            "regency": bool(report.regency.strip()),
            "description": bool(report.incident_description.strip()),
            "is_local_farmer": report.reporter_is_local is not None,
            "needs": bool(report.needs),
        }.get(field, False)
        return 1.0 if legacy_present else 0.0

    def _refresh_field_metadata(self, report: Report) -> None:
        verification = dict(report.field_verification or {})
        confidences = dict(report.field_confidences or {})
        reasons = dict(report.field_confidence_reasons or {})

        for field in ("category", "severity", "medical_needed"):
            if confidences.get(field, 0) > 0:
                verification[field] = "ai_extracted"

        if self._has_shared_location(report):
            verification["location"] = "verified_shared"
            confidences["location"] = 1.0
            for field in ("village", "district", "regency"):
                verification[field] = "replaced_by_shared_location"
        elif report.location_verification_status == "verified_geocoded":
            verification["location"] = "verified_geocoded"
            location_confidences: list[float] = []
            for field in ("village", "district", "regency"):
                if getattr(report, field).strip():
                    confidences[field] = max(float(confidences.get(field, 0)), 0.95)
                    verification[field] = "verified_geocoded"
                    location_confidences.append(confidences[field])
            confidences["location"] = min(location_confidences or [0.0])
        else:
            verification["location"] = report.location_verification_status
            location_confidences = [
                float(confidences.get(field, 0.0))
                for field in ("village", "district", "regency")
                if getattr(report, field).strip()
            ]
            confidences["location"] = min(location_confidences or [0.0])

        if report.incident_description.strip():
            verification["description"] = (
                "visually_consistent"
                if self._verified_evidence_count(report)
                else "self_reported"
            )
        if report.reporter_is_local is not None:
            verification["is_local_farmer"] = "self_reported"
        if report.needs:
            verification["needs"] = "ai_extracted"
        elif (report.follow_up_counts or {}).get("needs", 0) >= 1:
            verification["needs"] = "unknown_after_follow_up"
        else:
            verification["needs"] = "missing_or_uncertain"

        evidence_statuses = [
            str(item.get("status")) for item in (report.evidence_assessments or [])
        ]
        if "verified_visual" in evidence_statuses:
            verification["evidence"] = "verified_visual"
            reasons.pop("evidence", None)
        elif "supporting_only" in evidence_statuses:
            verification["evidence"] = "supporting_only"
            supporting = next(
                (
                    item
                    for item in reversed(report.evidence_assessments or [])
                    if item.get("status") == "supporting_only"
                ),
                {},
            )
            reasons["evidence"] = str(
                supporting.get("reason")
                or "Foto hanya memberi konteks dan belum cukup untuk verifikasi visual."
            )[:240]
        elif any(status.startswith("rejected_") for status in evidence_statuses):
            verification["evidence"] = "rejected"
            rejected = next(
                (
                    item
                    for item in reversed(report.evidence_assessments or [])
                    if str(item.get("status", "")).startswith("rejected_")
                ),
                {},
            )
            reasons["evidence"] = str(
                rejected.get("reason") or "Foto tidak lolos pemeriksaan visual."
            )[:240]
        elif report.evidence_urls:
            verification["evidence"] = "unverified"
            unverified = (report.evidence_assessments or [{}])[-1]
            reasons["evidence"] = str(
                unverified.get("reason")
                or "Foto belum berhasil diperiksa oleh model vision."
            )[:240]
        else:
            verification["evidence"] = "missing"
            reasons["evidence"] = "Foto bukti belum diunggah."
        confidences["evidence"] = self._evidence_confidence(report)

        report.field_confidences = {
            key: round(max(0.0, min(1.0, float(value))), 3)
            for key, value in confidences.items()
        }
        report.field_verification = verification
        report.field_confidence_reasons = reasons

    def _refresh_readiness(self, report: Report) -> None:
        missing_fields = self._missing_fields(report)
        if not self.form_required:
            score = min(len(report.evidence_urls or []), EVIDENCE_TARGET) * 25
            if self._has_shared_location(report):
                score += 45
            else:
                score += 15 if report.village.strip() else 0
                score += 15 if report.district.strip() else 0
                score += 15 if report.regency.strip() else 0
            score += 20 if report.incident_description.strip() else 0
            score += 10 if report.reporter_is_local is not None else 0
        else:
            score = round(
                READINESS_WEIGHTS["evidence"] * self._evidence_confidence(report)
            )
            if self._has_shared_location(report):
                score += round(
                    (
                        READINESS_WEIGHTS["village"]
                        + READINESS_WEIGHTS["district"]
                        + READINESS_WEIGHTS["regency"]
                    )
                    * self._field_confidence(report, "location")
                )
            else:
                for field in ("village", "district", "regency"):
                    if getattr(report, field).strip():
                        score += round(
                            READINESS_WEIGHTS[field]
                            * self._field_confidence(report, field)
                        )
            if report.incident_description.strip():
                score += round(
                    READINESS_WEIGHTS["description"]
                    * self._field_confidence(report, "description")
                )
            if report.reporter_is_local is not None:
                score += round(
                    READINESS_WEIGHTS["is_local_farmer"]
                    * self._field_confidence(report, "is_local_farmer")
                )
            if report.needs:
                score += round(
                    READINESS_WEIGHTS["needs"]
                    * self._field_confidence(report, "needs")
                )

            maximum_score = sum(READINESS_WEIGHTS.values())
            if (
                not report.needs
                and (report.follow_up_counts or {}).get("needs", 0) >= 1
            ):
                maximum_score -= READINESS_WEIGHTS["needs"]
            score = round(score * 100 / maximum_score) if maximum_score else 0

        if missing_fields:
            score = min(score, READINESS_THRESHOLD - 1)
        report.readiness_score = min(100, score)
        report.readiness_critique = [
            self._critique_for(field, report) for field in missing_fields
        ]
        report.status = (
            ReportStatus.needs_follow_up.value
            if score < READINESS_THRESHOLD
            else ReportStatus.complete.value
        )
        report.follow_up_question = (
            FOLLOW_UPS[missing_fields[0]] if missing_fields else None
        )
        report.review_required = (
            report.ai_confidence < 0.65
            or report.category == "unknown"
            or score < READINESS_THRESHOLD
            or report.reporter_is_local is False
            or (
                self.form_required
                and self._verified_evidence_count(report) < EVIDENCE_TARGET
            )
        )
        if not report.updates and report.response_status in {
            ResponseStatus.new.value,
            ResponseStatus.verified.value,
            ResponseStatus.rejected.value,
        }:
            report.response_status = (
                ResponseStatus.verified.value
                if not report.review_required
                and report.readiness_score >= READINESS_THRESHOLD
                and self._verified_evidence_count(report) >= EVIDENCE_TARGET
                and self._evidence_confidence(report) >= FIELD_CONFIDENCE_THRESHOLD
                else ResponseStatus.new.value
            )

    def _missing_fields(self, report: Report) -> list[str]:
        missing: list[str] = []
        evidence_count = (
            self._verified_evidence_count(report)
            if self.form_required
            else len(report.evidence_urls or [])
        )
        if evidence_count < EVIDENCE_TARGET:
            missing.append("evidence")
        if not self._has_shared_location(report):
            if (
                not report.village.strip()
                or (
                    self.form_required
                    and self._field_confidence(report, "village")
                    < FIELD_CONFIDENCE_THRESHOLD
                )
            ):
                missing.append("village")
            if (
                not report.district.strip()
                or (
                    self.form_required
                    and self._field_confidence(report, "district")
                    < FIELD_CONFIDENCE_THRESHOLD
                )
            ):
                missing.append("district")
            if (
                not report.regency.strip()
                or (
                    self.form_required
                    and self._field_confidence(report, "regency")
                    < FIELD_CONFIDENCE_THRESHOLD
                )
            ):
                missing.append("regency")
            admin_complete = all(
                value.strip()
                for value in [report.village, report.district, report.regency]
            )
            if (
                admin_complete
                and report.location_verification_status != "verified_geocoded"
            ):
                missing.append("location_verification")
        if (
            not report.incident_description.strip()
            or (
                self.form_required
                and self._field_confidence(report, "description")
                < FIELD_CONFIDENCE_THRESHOLD
            )
        ):
            missing.append("description")
        if (
            report.reporter_is_local is None
            or (
                self.form_required
                and self._field_confidence(report, "is_local_farmer")
                < FIELD_CONFIDENCE_THRESHOLD
            )
        ):
            missing.append("is_local_farmer")
        needs_follow_ups = (report.follow_up_counts or {}).get("needs", 0)
        if self.form_required and needs_follow_ups < 1 and (
            not report.needs
            or self._field_confidence(report, "needs") < FIELD_CONFIDENCE_THRESHOLD
        ):
            missing.append("needs")
        return [field for field in FOLLOW_UP_ORDER if field in missing]

    def _has_shared_location(self, report: Report) -> bool:
        return bool(
            report.location_shared
            and report.lat is not None
            and report.lon is not None
        )

    def _update_location_verification(
        self, report: Report, *, geo_found: bool
    ) -> None:
        if self._has_shared_location(report):
            report.location_verification_status = "verified_shared"
            return
        if geo_found and report.lat is not None and report.lon is not None:
            report.location_verification_status = "verified_geocoded"
            return
        if all(
            value.strip()
            for value in [report.village, report.district, report.regency]
        ):
            report.location_verification_status = "needs_verification"
            return
        report.location_verification_status = "missing"

    def _critique_for(self, field: str, report: Report) -> str:
        if field == "evidence" and not report.evidence_urls:
            return CRITIQUE_MESSAGES[field]
        if field == "evidence":
            statuses = {
                str(item.get("status")) for item in (report.evidence_assessments or [])
            }
            if "rejected_irrelevant" in statuses:
                return "foto belum menunjukkan dampak bencana atau kerusakan pertanian"
            if "rejected_mismatch" in statuses:
                return "isi foto tidak konsisten dengan deskripsi laporan"
            if "supporting_only" in statuses:
                return (
                    "foto satelit/aerial atau tangkapan layar hanya menjadi konteks; "
                    "dibutuhkan foto lapangan yang memperlihatkan dampak"
                )
            return "foto belum berhasil diverifikasi oleh AI vision"
        reason = (report.field_confidence_reasons or {}).get(field)
        if reason and self._field_confidence(report, field) < FIELD_CONFIDENCE_THRESHOLD:
            return reason
        return CRITIQUE_MESSAGES[field]

    def _readiness_message(self, report: Report) -> str:
        if report.readiness_score >= READINESS_THRESHOLD:
            return "✅ Informasinya cukup. Laporan siap ditindaklanjuti."
        if self.form_required:
            if not self.is_report_form(report.text or ""):
                return FORM_REQUIRED_MESSAGE
            reason = report.readiness_critique[0]
            return (
                f"Aku belum yakin pada bagian ini: {reason}.\n\n"
                f"{report.follow_up_question}\n\n{CANCEL_FOOTER}"
            )
        current_reason = report.readiness_critique[0]
        return (
            f"Masih kurang: {current_reason}.\n"
            f"{report.follow_up_question}\n\n"
            f"{CANCEL_FOOTER}"
        )

    def _tracking_message(self, report: Report) -> str:
        return (
            "Laporanmu tersimpan. Lihat status dan update lengkap di: "
            f"{self.public_url}/track/{report.public_token}"
        )

    def _normalized_command(self, text: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()

    def _is_greeting(self, text: str) -> bool:
        return self._normalized_command(text) in GREETINGS

    def _is_start_command(self, text: str) -> bool:
        return self._normalized_command(text) in START_COMMANDS

    def _is_form_copy_command(
        self, text: str, button_payload: str | None
    ) -> bool:
        return (
            (button_payload or "").strip().upper() == "FORM_COPY"
            or self._normalized_command(text) in {"salin form", "copy form"}
        )

    def _is_cancel_command(self, text: str) -> bool:
        return self._normalized_command(text) in {
            "batal",
            "cancel",
            "abort",
            "reset",
        }

    def _extract_description(
        self, text: str, classification: Classification, *, expected: bool
    ) -> str | None:
        labelled = re.search(
            r"deskripsi(?:[ \t]+dampak)?[ \t]*[:=-][ \t]*([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        if labelled:
            return labelled.group(1).strip()[:1000]
        metadata_label = re.compile(
            r"^(?:desa(?:/kelurahan)?|kelurahan|kecamatan|kota(?:/kabupaten)?|"
            r"kabupaten|kab\.?|lokasi|keparahan|medis|status petani|petani setempat|"
            r"bisa dihubungi|bantuan yang dibutuhkan|petani/penggarap di lokasi)\s*[:=-]|"
            r"^form laporan(?: petani)?$",
            flags=re.IGNORECASE,
        )
        cleaned = "\n".join(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not metadata_label.match(line.strip())
        ).strip()
        words = re.findall(r"\w+", cleaned)
        if expected and len(words) >= 3 and len(cleaned) >= 12:
            return cleaned[:1000]
        if classification.category != "unknown" and len(words) >= 4 and len(cleaned) >= 18:
            return cleaned[:1000]
        return None

    def _extract_description_from_reply(self, text: str, *, expected: bool) -> str | None:
        placeholder = Classification(
            category="other" if expected else "unknown",
            severity="unknown",
            medical_needed=False,
            missing_fields=[],
            needs=[],
            summary="",
            confidence=0,
            source="",
        )
        return self._extract_description(text, placeholder, expected=expected)

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

    def _extract_medical_answer(self, text: str, *, allow_bare: bool) -> bool | None:
        lower = text.lower().strip()
        if not lower:
            return None
        if any(
            phrase in lower
            for phrase in [
                "tidak perlu medis",
                "tidak butuh medis",
                "tidak ada korban",
                "tidak ada yang luka",
                "aman",
            ]
        ):
            return False
        if any(
            phrase in lower
            for phrase in [
                "perlu medis",
                "butuh medis",
                "ada korban",
                "ada yang luka",
                "butuh dokter",
                "butuh puskesmas",
            ]
        ) or re.search(r"\b(sakit|luka|medis|dokter|puskesmas|lansia|hamil)\b", lower):
            return True
        return self._extract_yes_no(lower) if allow_bare else None

    def _extract_profile_boolean(
        self, text: str, field: str, *, allow_bare: bool
    ) -> bool | None:
        lower = text.lower().strip()
        labels = {
            "is_farmer": ["status petani", "apakah petani"],
            "is_local_farmer": [
                "petani setempat",
                "petani lokal",
                "petani daerah ini",
                "warga setempat",
            ],
            "follow_up_available": [
                "bisa dihubungi",
                "bersedia dihubungi",
                "dihubungi lagi",
            ],
        }[field]
        for label in labels:
            match = re.search(
                rf"{re.escape(label)}\s*[:=-]\s*(ya|iya|benar|tidak|nggak|gak|bukan)",
                lower,
            )
            if match:
                return match.group(1) in {"ya", "iya", "benar"}

        negative_phrases = {
            "is_farmer": ["bukan petani", "tidak bekerja sebagai petani"],
            "is_local_farmer": [
                "bukan petani setempat",
                "bukan petani dari daerah ini",
                "bukan warga sini",
                "bukan dari daerah ini",
                "tidak tinggal di wilayah",
            ],
            "follow_up_available": [
                "tidak bisa dihubungi",
                "tidak bersedia dihubungi",
                "jangan hubungi",
            ],
        }[field]
        positive_phrases = {
            "is_farmer": [
                "saya petani",
                "kami petani",
                "saya penggarap",
                "lahan saya",
                "sawah saya",
                "kebun saya",
            ],
            "is_local_farmer": [
                "petani setempat",
                "petani lokal",
                "warga sini",
                "tinggal di wilayah",
                "bertani di wilayah",
            ],
            "follow_up_available": [
                "bisa dihubungi",
                "bersedia dihubungi",
                "siap dihubungi",
                "boleh dihubungi",
            ],
        }[field]
        if any(phrase in lower for phrase in negative_phrases):
            return False
        if any(phrase in lower for phrase in positive_phrases):
            return True
        return self._extract_yes_no(lower) if allow_bare else None

    def _extract_yes_no(self, text: str) -> bool | None:
        tokens = set(re.findall(r"\b[\w']+\b", text.lower()))
        if tokens.intersection({"tidak", "nggak", "gak", "bukan", "enggak"}):
            return False
        if tokens.intersection({"ya", "iya", "yes", "boleh", "bersedia", "benar"}):
            return True
        return None

    def _extract_admin_reply(self, text: str) -> str | None:
        cleaned = text.strip()
        if not cleaned or self._is_greeting(cleaned) or self._is_start_command(cleaned):
            return None
        cleaned = re.sub(
            r"^(?:desa(?:/kelurahan)?|kelurahan|kecamatan|kota(?:/kabupaten)?|kabupaten|kab\.?)"
            r"(?:\s+lokasi)?\s*[:=-]?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip(" ,.;")
        if not cleaned or len(cleaned) > 160 or len(cleaned.split()) > 8:
            return None
        return cleaned

    def _admin_location_label(self, report: Report) -> str:
        return ", ".join(
            value.strip()
            for value in [report.village, report.district, report.regency]
            if value and value.strip()
        )

    def _sync_location_label(self, report: Report) -> None:
        admin_label = self._admin_location_label(report)
        if admin_label:
            report.location_label = admin_label

    def _apply_shared_location_details(
        self, report: Report, geo: GeoResult | None
    ) -> None:
        if not self._has_shared_location(report) or geo is None:
            return
        # A WhatsApp pin replaces manual location fields. Reverse-geocoded
        # administrative fields are used when available; otherwise the exact
        # coordinates remain the safe fallback label.
        report.village = geo.village
        report.district = geo.district
        report.regency = geo.regency
        report.location_label = self._admin_location_label(report) or geo.label

    def _declines_evidence(self, text: str) -> bool:
        lower = text.lower()
        return any(
            phrase in lower
            for phrase in [
                "tidak ada foto",
                "tidak punya foto",
                "belum ada foto",
                "tidak bisa kirim foto",
                "tanpa foto",
            ]
        )

    def _normalize_evidence_urls(
        self, image_url: str | None, image_urls: list[str] | None
    ) -> list[str]:
        values = ([image_url] if image_url else []) + (image_urls or [])
        return self._merge_evidence_urls([], values)

    def _merge_evidence_urls(
        self, existing: list[str], incoming: list[str]
    ) -> list[str]:
        merged = list(existing)
        for url in incoming:
            cleaned = url.strip()
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
        return merged

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
        with db.no_autoflush:
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
        db.flush()
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
