from dataclasses import dataclass
import re


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    label: str
    region_name: str


class MockGeocoder:
    places = {
        "depok": GeoResult(-6.4025, 106.7942, "Depok", "Depok"),
        "cibubur": GeoResult(-6.3681, 106.9014, "Cibubur", "Cibubur"),
        "cimanggis": GeoResult(-6.3606, 106.8611, "Cimanggis", "Cimanggis"),
        "sayung": GeoResult(-6.9218, 110.5157, "Sayung, Demak", "Sayung"),
        "karanganyar": GeoResult(-6.9704, 110.7478, "Karanganyar, Demak", "Karanganyar Demak"),
        "demak": GeoResult(-6.8919, 110.6396, "Kabupaten Demak", "Demak"),
        "kudus": GeoResult(-6.8048, 110.8405, "Kabupaten Kudus", "Kudus"),
        "semarang": GeoResult(-6.9667, 110.4167, "Kota Semarang", "Semarang"),
    }

    _maps_query = re.compile(r"[?&]q=([\-0-9.]+)%2C([\-0-9.]+)")
    _maps_plain = re.compile(r"([\-0-9.]+),\s*([\-0-9.]+)")

    def resolve(self, text: str, lat: float | None = None, lon: float | None = None, label: str | None = None) -> GeoResult | None:
        if lat is not None and lon is not None:
            display_label = label or "Shared WhatsApp location"
            region_name = f"Area {lat:.2f},{lon:.2f}"
            if label:
                lower_label = label.lower()
                for key, known_place in self.places.items():
                    if key in lower_label:
                        region_name = known_place.label
                        break
                else:
                    region_name = ", ".join(
                        part.strip() for part in label.split(",")[:2] if part.strip()
                    ) or region_name
            return GeoResult(lat, lon, display_label, region_name)

        lower = f"{text} {label or ''}".lower()

        maps_match = self._maps_query.search(text) or self._maps_plain.search(text)
        if maps_match:
            lat_value = float(maps_match.group(1))
            lon_value = float(maps_match.group(2))
            return GeoResult(
                lat_value,
                lon_value,
                label or "Shared WhatsApp location",
                label or f"Shared Location {lat_value:.4f},{lon_value:.4f}",
            )

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
