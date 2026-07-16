from sqlalchemy.orm import Session

from app.models import Region, Resource
from app.services.triage import TriageService


def seed(db: Session) -> None:
    if db.query(Resource).count() == 0:
        db.add_all(
            [
                Resource(name="Puskesmas Sayung I", kind="health_post", lat=-6.9242, lon=110.5092, stock_summary="basic medicine, 2 nurses, ambulance standby"),
                Resource(name="Gudang BPBD Demak", kind="relief_stock", lat=-6.8952, lon=110.6381, stock_summary="rice 1.2t, blankets 300, pumps 4"),
                Resource(name="RSUD Sunan Kalijaga", kind="hospital", lat=-6.8895, lon=110.6364, stock_summary="ER open, referral ambulance available"),
                Resource(name="Posko Kudus Selatan", kind="relief_post", lat=-6.8221, lon=110.8452, stock_summary="water purifier, tents 20, food packs 500"),
            ]
        )
        db.commit()

    if db.query(Region).count() == 0:
        triage = TriageService()
        triage.ingest(db, sender="seed", text="banjir mulai naik di Sayung Demak, air setinggi lutut, tidak ada korban")
        triage.ingest(db, sender="seed", text="hujan deras di Kudus, sawah rusak sedang, aman tidak perlu medis")

