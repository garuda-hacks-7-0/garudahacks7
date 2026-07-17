class MockWeatherRisk:
    """BMKG-shaped enrichment. Replace with a real fetcher later."""

    baseline = {
        "Demak": 0.72,
        "Sayung": 0.84,
        "Sayung, Demak": 0.84,
        "Karanganyar Demak": 0.66,
        "Karanganyar, Demak": 0.66,
        "Kudus": 0.52,
        "Semarang": 0.58,
        "Shared Location": 0.45,
    }

    def risk_for_region(self, region_name: str) -> float:
        return self.baseline.get(region_name, 0.35)

