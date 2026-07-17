from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
import re


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    label: str
    region_name: str
    village: str = ""
    district: str = ""
    regency: str = ""


GENERIC_SHARED_LOCATION_LABELS = {
    "shared whatsapp location",
    "shared location",
    "current location",
    "dropped pin",
}


def is_generic_location_label(label: str | None) -> bool:
    return not label or label.strip().lower() in GENERIC_SHARED_LOCATION_LABELS


class MockGeocoder:
    places = {
        "depok": GeoResult(
            -6.4025, 106.7942, "Depok", "Depok", regency="Kota Depok"
        ),
        "cibubur": GeoResult(
            -6.3681,
            106.9014,
            "Cibubur",
            "Cibubur",
            village="Cibubur",
            district="Ciracas",
            regency="Kota Jakarta Timur",
        ),
        "cimanggis": GeoResult(
            -6.3606,
            106.8611,
            "Cimanggis",
            "Cimanggis",
            district="Cimanggis",
            regency="Kota Depok",
        ),
        "sayung": GeoResult(
            -6.9218,
            110.5157,
            "Sayung, Demak",
            "Sayung",
            village="Sayung",
            district="Sayung",
            regency="Kabupaten Demak",
        ),
        "karanganyar": GeoResult(
            -6.9704,
            110.7478,
            "Karanganyar, Demak",
            "Karanganyar Demak",
            village="Karanganyar",
            district="Karanganyar",
            regency="Kabupaten Demak",
        ),
        "demak": GeoResult(
            -6.8919,
            110.6396,
            "Kabupaten Demak",
            "Demak",
            district="Demak",
            regency="Kabupaten Demak",
        ),
        "kudus": GeoResult(
            -6.8048,
            110.8405,
            "Kabupaten Kudus",
            "Kudus",
            district="Kota Kudus",
            regency="Kabupaten Kudus",
        ),
        "semarang": GeoResult(
            -6.9667,
            110.4167,
            "Kota Semarang",
            "Semarang",
            regency="Kota Semarang",
        ),
    }

    _maps_query = re.compile(r"[?&]q=([\-0-9.]+)%2C([\-0-9.]+)")
    _maps_plain = re.compile(r"([\-0-9.]+),\s*([\-0-9.]+)")

    def resolve(self, text: str, lat: float | None = None, lon: float | None = None, label: str | None = None) -> GeoResult | None:
        if lat is not None and lon is not None:
            reverse = self._reverse_coordinates(round(lat, 5), round(lon, 5))
            if reverse is not None:
                return GeoResult(
                    lat,
                    lon,
                    reverse.label,
                    reverse.region_name,
                    village=reverse.village,
                    district=reverse.district,
                    regency=reverse.regency,
                )
            display_label = (
                label
                if not is_generic_location_label(label)
                else f"{lat:.5f}, {lon:.5f}"
            )
            return GeoResult(
                lat,
                lon,
                display_label,
                display_label or f"Area {lat:.2f},{lon:.2f}",
            )

        lower = f"{text} {label or ''}".lower()

        maps_match = self._maps_query.search(text) or self._maps_plain.search(text)
        if maps_match:
            lat_value = float(maps_match.group(1))
            lon_value = float(maps_match.group(2))
            return self.resolve(text, lat_value, lon_value, label)

        for key, result in self.places.items():
            if key in lower:
                return result

        # Dynamic OpenStreetMap Nominatim geocoding fallback
        clean_text = text.strip()
        if not clean_text:
            return None

        query_candidate = None
        if len(clean_text.split()) > 3:
            match = re.search(r"\b(?:di|kecamatan|desa|kabupaten|kota|daerah)\s+([a-zA-Z\s]{3,30})", clean_text, re.IGNORECASE)
            if match:
                query_candidate = match.group(1).strip()
                # Clean up trailing descriptions
                query_candidate = re.split(r'\b(?:ada|dan|yang|dengan|rt|rw|terjadi)\b', query_candidate, flags=re.IGNORECASE)[0].strip()
            else:
                # Try the first word if it doesn't match a blacklist of common words
                words = [w.strip(".,!?\"'()[]{}") for w in clean_text.split()]
                if words:
                    first_word = words[0]
                    if first_word.lower() not in ["ada", "banjir", "tolong", "saya", "gempa", "kebakaran", "hujan", "badai", "hama", "rusak", "hancur", "terjadi", "minta", "butuh", "darurat", "info", "laporan", "kejadian", "terjebak", "luka", "sakit", "medis"]:
                        query_candidate = first_word
        else:
            query_candidate = clean_text

        if query_candidate:
            search_query = re.sub(r'\b(?:di|kecamatan|desa|kabupaten|kota|daerah|provinsi|jalan)\b', '', query_candidate, flags=re.IGNORECASE).strip()
        else:
            search_query = None

        if search_query and len(search_query) >= 3:
            import urllib.request
            import urllib.parse
            import json
            import ssl

            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
                "q": search_query,
                "format": "json",
                "limit": 1
            })
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "GarudaHacksDisasterTriageDemo/1.0 (daffaismail@gmail.com)"}
            )
            try:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=3, context=context) as response:
                    data = json.loads(response.read().decode())
                    if data:
                        place = data[0]
                        lat_val = float(place["lat"])
                        lon_val = float(place["lon"])
                        display_name = place["display_name"]
                        region_name = display_name.split(",")[0].strip()
                        return GeoResult(lat_val, lon_val, display_name, region_name)
            except Exception:
                pass

        return None

    @lru_cache(maxsize=256)
    def _reverse_coordinates(self, lat: float, lon: float) -> GeoResult | None:
        nearby = min(
            self.places.values(),
            key=lambda place: self._distance_km(lat, lon, place.lat, place.lon),
        )
        if (
            self._distance_km(lat, lon, nearby.lat, nearby.lon) <= 5
            and (nearby.village or nearby.district or nearby.regency)
        ):
            label = ", ".join(
                value
                for value in [nearby.village, nearby.district, nearby.regency]
                if value
            )
            return GeoResult(
                lat,
                lon,
                label or nearby.label,
                nearby.region_name,
                village=nearby.village,
                district=nearby.district,
                regency=nearby.regency,
            )

        import json
        import urllib.parse
        import urllib.request

        url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": 18,
            }
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "GarudaHacksDisasterTriageDemo/1.0 "
                "(daffaismail@gmail.com)"
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                result = json.loads(response.read().decode())
        except Exception:
            return None

        address = result.get("address") or {}
        village = self._first_address_value(
            address, "village", "town", "hamlet", "suburb", "neighbourhood"
        )
        district = self._first_address_value(
            address, "municipality", "city_district", "district"
        )
        regency = self._first_address_value(
            address, "county", "city", "state_district"
        )
        label = ", ".join(
            value for value in [village, district, regency] if value
        )
        if not label:
            label = result.get("display_name", "").strip()
        if not label:
            return None
        return GeoResult(
            lat,
            lon,
            label,
            regency or district or village or label.split(",")[0],
            village=village,
            district=district,
            regency=regency,
        )

    @staticmethod
    def _first_address_value(address: dict[str, object], *keys: str) -> str:
        for key in keys:
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _distance_km(
        lat_a: float, lon_a: float, lat_b: float, lon_b: float
    ) -> float:
        lat1, lon1, lat2, lon2 = map(
            radians, [lat_a, lon_a, lat_b, lon_b]
        )
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        haversine = (
            sin(dlat / 2) ** 2
            + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        )
        return 6371 * 2 * asin(sqrt(haversine))
