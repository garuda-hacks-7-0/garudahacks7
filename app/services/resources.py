from math import asin, cos, radians, sin, sqrt

from sqlalchemy.orm import Session

from app.models import LocalContact, Resource


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(a))


class ResourceService:
    def nearest(self, db: Session, lat: float, lon: float, limit: int = 3) -> list[Resource]:
        resources = db.query(Resource).all()
        return sorted(resources, key=lambda item: km_between(lat, lon, item.lat, item.lon))[:limit]

    def nearest_contacts(
        self, db: Session, lat: float, lon: float, limit: int = 3
    ) -> list[LocalContact]:
        contacts = db.query(LocalContact).all()
        return sorted(
            contacts,
            key=lambda item: km_between(lat, lon, item.lat, item.lon),
        )[:limit]

