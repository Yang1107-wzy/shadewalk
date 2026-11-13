"""Current weather from the Hong Kong Observatory open data API."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from shadewalk.data.cache import USER_AGENT

__all__ = ["CurrentWeather", "current_weather", "parse_rhrread"]

HKO_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"


@dataclass(frozen=True)
class CurrentWeather:
    station: str
    temperature_c: float | None
    uv_index: float | None
    humidity_pct: float | None
    update_time: str | None


def parse_rhrread(payload: dict, station: str = "Hong Kong Observatory") -> CurrentWeather:
    """Extract one station's reading from an HKO ``rhrread`` JSON payload."""
    temp = None
    for row in (payload.get("temperature") or {}).get("data", []):
        if row.get("place") == station:
            temp = float(row["value"])
            break
    uv_rows = (
        (payload.get("uvindex") or {}).get("data", [])
        if isinstance(payload.get("uvindex"), dict)
        else []
    )
    uv = float(uv_rows[0]["value"]) if uv_rows else None
    hum_rows = (payload.get("humidity") or {}).get("data", [])
    hum = float(hum_rows[0]["value"]) if hum_rows else None
    return CurrentWeather(station, temp, uv, hum, payload.get("updateTime"))


def current_weather(station: str = "Hong Kong Observatory", timeout: float = 20) -> CurrentWeather:
    """Fetch the latest regional weather reading (not cached)."""
    resp = requests.get(
        HKO_URL,
        params={"dataType": "rhrread", "lang": "en"},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return parse_rhrread(resp.json(), station)
