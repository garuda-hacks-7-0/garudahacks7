from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    category: str
    severity: str
    medical_needed: bool
    missing_fields: list[str]


SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class MockClassifier:
    """Keyword classifier shaped like the output expected from GPT/Claude."""

    def classify(self, text: str, image_url: str | None = None) -> Classification:
        lower = text.lower()
        category = "unknown"
        if any(word in lower for word in ["banjir", "kebanjiran", "flood", "air"]):
            category = "flood"
        elif any(word in lower for word in ["hama", "wereng", "pest"]):
            category = "crop_pest"
        elif any(word in lower for word in ["rusak", "puso", "gagal panen", "crop"]):
            category = "crop_damage"
        elif image_url:
            category = "field_damage_photo"

        negated_medical = any(
            phrase in lower
            for phrase in ["tidak perlu medis", "tidak ada korban", "tidak butuh medis", "aman"]
        )
        medical_needed = (
            any(word in lower for word in ["sakit", "luka", "medis", "dokter", "puskesmas", "lansia", "hamil"])
            and not negated_medical
        )

        severity = "medium"
        if any(word in lower for word in ["darurat", "terjebak", "putus", "hilang", "evakuasi"]):
            severity = "critical"
        elif any(word in lower for word in ["parah", "besar", "tinggi", "dada", "arus", "gagal panen"]):
            severity = "high"
        elif any(word in lower for word in ["sedikit", "ringan", "surut"]):
            severity = "low"

        missing_fields: list[str] = []
        if not any(word in lower for word in ["demak", "sayung", "karanganyar", "kudus", "semarang"]) and "lat:" not in lower:
            missing_fields.append("location")
        if not any(word in lower for word in ["ringan", "sedang", "parah", "darurat", "besar", "putus", "tinggi", "lutut", "dada"]):
            missing_fields.append("severity")
        if not any(word in lower for word in ["medis", "sakit", "luka", "tidak ada korban", "aman", "lansia", "hamil"]):
            missing_fields.append("medical_needed")

        return Classification(category, severity, medical_needed, missing_fields[:3])
