from dataclasses import dataclass


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    label: str
    region_name: str


class MockGeocoder:
    places = {
        "sayung": GeoResult(-6.9218, 110.5157, "Sayung, Demak", "Sayung"),
        "karanganyar": GeoResult(-6.9704, 110.7478, "Karanganyar, Demak", "Karanganyar Demak"),
        "demak": GeoResult(-6.8919, 110.6396, "Kabupaten Demak", "Demak"),
        "kudus": GeoResult(-6.8048, 110.8405, "Kabupaten Kudus", "Kudus"),
        "semarang": GeoResult(-6.9667, 110.4167, "Kota Semarang", "Semarang"),
    }

    def resolve(self, text: str, lat: float | None = None, lon: float | None = None, label: str | None = None) -> GeoResult | None:
        if lat is not None and lon is not None:
            return GeoResult(lat, lon, label or "Shared WhatsApp location", label or "Shared Location")

        lower = f"{text} {label or ''}".lower()
        for key, result in self.places.items():
            if key in lower:
                return result
        return None
