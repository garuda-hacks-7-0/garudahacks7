from sqlalchemy.orm import Session

from app.models import (
    LocalContact,
    Organization,
    Region,
    Report,
    ReportUpdate,
    Resource,
)
from app.services.classifier import MockClassifier
from app.services.triage import TriageService


ORGANIZATIONS = [
    ("PMI Demak", "volunteer"),
    ("BPBD Kabupaten Demak", "government"),
    ("Pemerintah Desa Sayung", "village"),
    ("MDMC Kudus", "volunteer"),
]


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


def seed(db: Session) -> None:
    _seed_organizations(db)
    _seed_contacts(db)
    _seed_resources(db)
    _seed_reports(db)
    _seed_updates(db)


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
    triage = TriageService(classifier=classifier)
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
                location_label=label,
                region=region,
            )
        )
        touched_regions.add(label)
    db.commit()
    for label in touched_regions:
        triage.recalculate_region(db, regions[label])


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
