from sqlalchemy.orm import Session

from app.models import (
    FarmerProfile,
    LocalContact,
    Organization,
    Region,
    Report,
    ReportUpdate,
    Resource,
)
from app.services.classifier import MockClassifier
from app.services.geocoder import MockGeocoder, is_generic_location_label
from app.services.triage import TriageService


ORGANIZATIONS = [
    ("PMI Demak", "volunteer"),
    ("BPBD Kabupaten Demak", "government"),
    ("Pemerintah Desa Sayung", "village"),
    ("MDMC Kudus", "volunteer"),
]

ORGANIZATION_DETAILS = {
    "PMI Demak": {
        "email": "markas@pmidemak.demo",
        "phone": "+628111000501",
        "address": "Kabupaten Demak, Jawa Tengah",
        "contact_name": "Posko PMI Demak",
        "contact_role": "Koordinator piket",
        "operational_areas": ["Demak", "Sayung"],
    },
    "BPBD Kabupaten Demak": {
        "email": "pusdalops@bpbd-demak.demo",
        "phone": "+628111000502",
        "address": "Kabupaten Demak, Jawa Tengah",
        "contact_name": "Pusdalops BPBD Demak",
        "contact_role": "Petugas piket",
        "operational_areas": ["Kabupaten Demak"],
    },
    "Pemerintah Desa Sayung": {
        "email": "kantor@desasayung.demo",
        "phone": "+628111000102",
        "address": "Desa Sayung, Kabupaten Demak",
        "contact_name": "Kantor Desa Sayung",
        "contact_role": "Pelayanan desa",
        "operational_areas": ["Desa Sayung"],
    },
    "MDMC Kudus": {
        "email": "posko@mdmckudus.demo",
        "phone": "+628111000503",
        "address": "Kabupaten Kudus, Jawa Tengah",
        "contact_name": "Posko MDMC Kudus",
        "contact_role": "Koordinator respons",
        "operational_areas": ["Kudus", "Demak"],
    },
}


DEMO_REPORTS = [
    ("Sayung, Demak", -6.9218, 110.5157, "banjir parah setinggi dada, jalan putus, perlu evakuasi dan medis untuk lansia"),
    ("Sayung, Demak", -6.9188, 110.5201, "banjir sedang setinggi lutut, sawah terendam, tidak ada korban, butuh pompa"),
    ("Sayung, Demak", -6.9261, 110.5112, "banjir besar dan arus tinggi, ada warga luka perlu medis dan air bersih"),
    ("Sayung, Demak", -6.9144, 110.5075, "banjir ringan mulai surut, tanaman padi rusak, aman tidak perlu medis"),
    ("Sayung, Demak", -6.9302, 110.5240, "darurat banjir, keluarga terjebak dan butuh evakuasi, ada orang sakit"),
    ("Sayung, Demak", -6.9237, 110.5291, "banjir sedang di sawah, butuh benih pengganti, tidak ada korban"),
    ("Karanganyar, Demak", -6.9704, 110.7478, "gagal panen parah setelah banjir besar, aman tidak perlu medis, butuh benih"),
    ("Karanganyar, Demak", -6.9651, 110.7392, "banjir sedang merendam gudang gabah, tidak ada korban, butuh pangan"),
    ("Karanganyar, Demak", -6.9760, 110.7530, "serangan wereng parah dan tanaman rusak, aman tidak perlu medis"),
    ("Karanganyar, Demak", -6.9682, 110.7588, "banjir ringan sudah surut tetapi sawah rusak, tidak ada korban"),
    ("Demak", -6.8919, 110.6396, "banjir besar setinggi dada, warga sakit perlu puskesmas dan evakuasi"),
    ("Demak", -6.8871, 110.6470, "angin badai parah merobohkan lumbung, satu orang luka perlu medis"),
    ("Demak", -6.8998, 110.6322, "banjir sedang menggenangi lahan, aman tidak ada korban, butuh pompa"),
    ("Demak", -6.9040, 110.6415, "hama wereng sedang menyebar, tidak perlu medis, butuh pestisida"),
    ("Kudus", -6.8048, 110.8405, "banjir besar dan jalan putus, perlu evakuasi, ada warga sakit"),
    ("Kudus", -6.8120, 110.8330, "sawah rusak sedang setelah hujan, aman tidak perlu medis, butuh benih"),
    ("Kudus", -6.7980, 110.8490, "banjir ringan mulai surut, tidak ada korban, butuh air bersih"),
    ("Kudus", -6.8201, 110.8572, "kekeringan parah membuat padi gagal panen, tidak perlu medis"),
    ("Semarang", -6.9667, 110.4167, "banjir sedang di lahan pinggir kota, aman tidak ada korban"),
    ("Semarang", -6.9722, 110.4234, "angin besar parah merusak rumah dan sawah, satu warga luka perlu medis"),
    ("Semarang", -6.9583, 110.4102, "banjir ringan sudah surut, tanaman rusak, tidak perlu medis"),
    ("Semarang", -6.9810, 110.4310, "kebakaran lahan darurat meluas, butuh evakuasi dan bantuan medis"),
    ("Depok", -6.4025, 106.7942, "banjir sedang di kebun, aman tidak ada korban, butuh pompa"),
    ("Depok", -6.4102, 106.8010, "longsor parah menutup akses lahan, ada warga luka perlu medis"),
]

SEED_EVIDENCE_URLS = [
    "https://images.unsplash.com/photo-1547683905-f686c993aae5?auto=format&fit=crop&w=900&q=70",
    "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=70",
]


def seed(db: Session) -> None:
    _seed_organizations(db)
    _backfill_organizations(db)
    _seed_pending_organization(db)
    _seed_contacts(db)
    _seed_resources(db)
    _seed_reports(db)
    _backfill_shared_locations(db)
    _backfill_seed_profiles(db)
    _seed_updates(db)
    _backfill_update_documentation(db)


def _seed_organizations(db: Session) -> None:
    if db.query(Organization).count() > 0:
        return
    db.add_all(
        [
            Organization(name=name, type=organization_type, verified=True)
            for name, organization_type in ORGANIZATIONS
        ]
    )
    db.commit()


def _backfill_organizations(db: Session) -> None:
    for organization in db.query(Organization).filter(Organization.verified.is_(True)):
        details = ORGANIZATION_DETAILS.get(organization.name, {})
        organization.applicant_kind = "organization"
        organization.registration_status = "verified"
        organization.email = organization.email or details.get("email", "")
        organization.phone = organization.phone or details.get("phone", "")
        organization.address = organization.address or details.get("address", "")
        organization.contact_name = organization.contact_name or details.get(
            "contact_name", ""
        )
        organization.contact_role = organization.contact_role or details.get(
            "contact_role", ""
        )
        organization.operational_areas = (
            organization.operational_areas
            or details.get("operational_areas", [])
        )
        organization.document_links = organization.document_links or {
            "legal": "https://example.org/demo/sk-lembaga.pdf",
            "mandate": "https://example.org/demo/surat-mandat.pdf",
        }
        db.add(organization)
    db.commit()


def _seed_pending_organization(db: Session) -> None:
    name = "Komunitas Relawan Tani Muria"
    if db.query(Organization).filter(Organization.name == name).one_or_none():
        return
    db.add(
        Organization(
            name=name,
            type="community",
            verified=False,
            applicant_kind="organization",
            registration_status="pending",
            email="relawan@muria.demo",
            phone="+628111000601",
            address="Kudus, Jawa Tengah",
            contact_name="Ayu Lestari",
            contact_role="Koordinator relawan",
            operational_areas=["Kudus", "Pati", "Demak"],
            document_links={
                "legal": "https://example.org/demo/sk-komunitas.pdf",
                "mandate": "https://example.org/demo/surat-mandat-ayu.pdf",
                "portfolio": "https://example.org/demo/portofolio-muria.pdf",
            },
        )
    )
    db.commit()


def _seed_contacts(db: Session) -> None:
    if db.query(LocalContact).count() > 0:
        return
    db.add_all(
        [
            LocalContact(name="Posko PMI Sayung", type="posko", phone="+628111000101", lat=-6.9225, lon=110.5120),
            LocalContact(name="Kantor Desa Sayung", type="desa", phone="+628111000102", lat=-6.9198, lon=110.5169),
            LocalContact(name="Puskesmas Sayung I", type="puskesmas", phone="+62291686230", lat=-6.9242, lon=110.5092),
            LocalContact(name="Posko BPBD Demak", type="posko", phone="+628111000201", lat=-6.8952, lon=110.6381),
            LocalContact(name="Balai Desa Karanganyar", type="desa", phone="+628111000301", lat=-6.9712, lon=110.7460),
            LocalContact(name="Posko Kudus Selatan", type="posko", phone="+628111000401", lat=-6.8221, lon=110.8452),
            LocalContact(name="Puskesmas Genuk", type="puskesmas", phone="+62246580192", lat=-6.9615, lon=110.4740),
        ]
    )
    db.commit()


def _seed_resources(db: Session) -> None:
    if db.query(Resource).count() > 0:
        return
    db.add_all(
        [
            Resource(name="Puskesmas Sayung I", kind="health_post", lat=-6.9242, lon=110.5092, stock_summary="obat dasar, 2 perawat, ambulans siaga"),
            Resource(name="Gudang BPBD Demak", kind="relief_stock", lat=-6.8952, lon=110.6381, stock_summary="beras 1,2 ton, 300 selimut, 4 pompa"),
            Resource(name="RSUD Sunan Kalijaga", kind="hospital", lat=-6.8895, lon=110.6364, stock_summary="IGD buka, ambulans rujukan tersedia"),
            Resource(name="Posko Kudus Selatan", kind="relief_post", lat=-6.8221, lon=110.8452, stock_summary="pemurni air, 20 tenda, 500 paket pangan"),
        ]
    )
    db.commit()


def _seed_reports(db: Session) -> None:
    if db.query(Report).count() >= len(DEMO_REPORTS):
        return
    classifier = MockClassifier()
    triage = TriageService(
        classifier=classifier,
        privacy_consent_required=False,
        form_required=False,
    )
    existing_senders = {sender for (sender,) in db.query(Report.sender).all()}
    regions = {region.name: region for region in db.query(Region).all()}
    touched_regions: set[str] = set()
    for index, (label, lat, lon, text) in enumerate(DEMO_REPORTS, start=1):
        sender = f"seed-{index:02d}"
        if sender in existing_senders:
            continue
        classification = classifier.classify(text)
        region = regions.get(label)
        if region is None:
            weather_risk = triage.weather.risk_for_region(label)
            region = Region(
                name=label,
                lat=lat,
                lon=lon,
                weather_risk=weather_risk,
                risk_score=weather_risk,
            )
            regions[label] = region
            db.add(region)
        db.add(
            Report(
                sender=sender,
                text=text,
                image_url=(
                    "https://images.unsplash.com/photo-1547683905-f686c993aae5?auto=format&fit=crop&w=900&q=70"
                    if index % 4 == 0
                    else None
                ),
                category=classification.category,
                severity=classification.severity,
                medical_needed=classification.medical_needed,
                needs=classification.needs,
                ai_summary=classification.summary,
                ai_confidence=classification.confidence,
                triage_source=classification.source,
                review_required=classification.confidence < 0.65,
                status="complete",
                response_status="new",
                lat=lat,
                lon=lon,
                location_verification_status="verified_geocoded",
                location_label=label,
                region=region,
            )
        )
        touched_regions.add(label)
    db.commit()
    for label in touched_regions:
        triage.recalculate_region(db, regions[label])


def _backfill_seed_profiles(db: Session) -> None:
    reports = db.query(Report).filter(Report.sender.like("seed-%")).all()
    for report in reports:
        profile = (
            db.query(FarmerProfile)
            .filter(FarmerProfile.sender == report.sender)
            .one_or_none()
        )
        if profile is None:
            profile = FarmerProfile(sender=report.sender)
        profile.is_farmer = True
        profile.is_local_farmer = True
        profile.available_for_follow_up = True
        profile.home_location = report.location_label
        profile.profile_summary = (
            f"petani/penggarap; petani setempat; bersedia dihubungi; "
            f"wilayah {report.location_label}"
        )
        report.farmer_profile = profile
        report.incident_description = report.incident_description or report.text
        location_parts = [part.strip() for part in (report.location_label or "").split(",")]
        report.village = report.village or (location_parts[0] if len(location_parts) > 1 else "Pusat")
        report.district = report.district or (location_parts[0] if location_parts else "Pusat")
        report.regency = report.regency or (location_parts[-1] if location_parts else "Demo")
        report.evidence_urls = SEED_EVIDENCE_URLS
        report.image_url = SEED_EVIDENCE_URLS[0]
        report.evidence_unavailable = False
        report.severity_confirmed = True
        report.medical_status_confirmed = True
        report.reporter_is_farmer = True
        report.reporter_is_local = True
        report.follow_up_available = True
        report.readiness_score = 100
        report.readiness_critique = []
        report.status = "complete"
        report.review_required = (
            report.ai_confidence < 0.65 or report.category == "unknown"
        )
        db.add_all([profile, report])
    db.commit()


def _backfill_shared_locations(db: Session) -> None:
    geocoder = MockGeocoder()
    reports = (
        db.query(Report)
        .filter(
            Report.location_shared.is_(True),
            Report.lat.is_not(None),
            Report.lon.is_not(None),
        )
        .all()
    )
    for report in reports:
        if not is_generic_location_label(report.location_label):
            continue
        geo = geocoder.resolve("", report.lat, report.lon)
        if geo is None or not (geo.village or geo.district or geo.regency):
            continue
        report.village = geo.village
        report.district = geo.district
        report.regency = geo.regency
        report.location_label = ", ".join(
            value
            for value in [geo.village, geo.district, geo.regency]
            if value
        )
        db.add(report)
    db.commit()


def _seed_updates(db: Session) -> None:
    if db.query(ReportUpdate).count() > 0:
        return
    organizations = db.query(Organization).order_by(Organization.id).all()
    reports = db.query(Report).order_by(Report.id).limit(8).all()
    if not organizations:
        return
    statuses = ["verified", "in_progress", "resolved"]
    for index, report in enumerate(reports):
        status = statuses[index % len(statuses)]
        organization = organizations[index % len(organizations)]
        report.response_status = status
        db.add(
            ReportUpdate(
                report=report,
                status=status,
                note="Pembaruan demo dari tim lapangan.",
                organization=organization,
            )
        )
    db.commit()


def _backfill_update_documentation(db: Session) -> None:
    updates = db.query(ReportUpdate).order_by(ReportUpdate.id).limit(8).all()
    for index, update in enumerate(updates):
        if not update.documentation_urls:
            update.documentation_urls = [
                SEED_EVIDENCE_URLS[index % len(SEED_EVIDENCE_URLS)]
            ]
        if not update.note or update.note == "Pembaruan demo dari tim lapangan.":
            update.note = {
                "verified": "Lokasi dan kebutuhan sudah diverifikasi oleh tim lapangan.",
                "in_progress": "Tim membawa bantuan awal dan mengecek akses menuju lahan.",
                "resolved": "Penanganan awal selesai dan kondisi lahan masuk pemantauan.",
            }.get(update.status, "Pembaruan dari tim lapangan.")
        db.add(update)
    db.commit()
