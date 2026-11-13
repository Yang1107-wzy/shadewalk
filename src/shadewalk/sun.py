"""Solar position (NOAA General Solar Position algorithm), vectorised with numpy.

The implementation follows the NOAA Solar Calculator spreadsheet
(https://gml.noaa.gov/grad/solcalc/calcdetails.html). Accuracy is well within
0.1 degrees for dates between 1800 and 2100, which is far below the
uncertainty of building heights used to cast shadows.

Angles are in degrees. Azimuth is measured clockwise from geographic north
(0 = N, 90 = E, 180 = S, 270 = W).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

__all__ = ["SunPosition", "solar_position"]


@dataclass(frozen=True)
class SunPosition:
    """Sun altitude (elevation above horizon) and azimuth in degrees."""

    altitude: float
    azimuth: float

    @property
    def is_up(self) -> bool:
        return self.altitude > 0.0


def _to_utc_index(when: datetime | pd.Timestamp | pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex([when]) if not isinstance(when, pd.DatetimeIndex) else when
    if idx.tz is None:
        raise ValueError("datetime must be timezone-aware (e.g. Asia/Hong_Kong)")
    return idx.tz_convert(timezone.utc)


def _solar_arrays(
    when: datetime | pd.Timestamp | pd.DatetimeIndex, lat: float, lon: float
) -> tuple[np.ndarray, np.ndarray]:
    utc = _to_utc_index(when)
    # Julian day (UNIX epoch 1970-01-01 is JD 2440587.5)
    days = (utc.tz_convert(None) - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)
    jd = np.asarray(days, dtype=float) + 2440587.5
    jc = (jd - 2451545.0) / 36525.0  # Julian century

    geom_mean_long = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360.0)
    geom_mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    m = np.radians(geom_mean_anom)
    eq_ctr = (
        np.sin(m) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + np.sin(2 * m) * (0.019993 - 0.000101 * jc)
        + np.sin(3 * m) * 0.000289
    )
    true_long = geom_mean_long + eq_ctr
    omega = np.radians(125.04 - 1934.136 * jc)
    app_long = true_long - 0.00569 - 0.00478 * np.sin(omega)
    mean_obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq_corr = mean_obliq + 0.00256 * np.cos(omega)
    decl = np.degrees(np.arcsin(np.sin(np.radians(obliq_corr)) * np.sin(np.radians(app_long))))

    y = np.tan(np.radians(obliq_corr / 2)) ** 2
    l0 = np.radians(geom_mean_long)
    eq_time = 4 * np.degrees(
        y * np.sin(2 * l0)
        - 2 * ecc * np.sin(m)
        + 4 * ecc * y * np.sin(m) * np.cos(2 * l0)
        - 0.5 * y * y * np.sin(4 * l0)
        - 1.25 * ecc * ecc * np.sin(2 * m)
    )

    minutes_utc = (utc.hour * 60 + utc.minute + utc.second / 60 + utc.microsecond / 6e7).to_numpy(
        dtype=float
    )
    true_solar_time = np.mod(minutes_utc + eq_time + 4 * lon, 1440.0)
    hour_angle = np.where(
        true_solar_time / 4 < 0, true_solar_time / 4 + 180, true_solar_time / 4 - 180
    )

    lat_r, decl_r, ha_r = np.radians(lat), np.radians(decl), np.radians(hour_angle)
    cos_zen = np.sin(lat_r) * np.sin(decl_r) + np.cos(lat_r) * np.cos(decl_r) * np.cos(ha_r)
    zenith = np.degrees(np.arccos(np.clip(cos_zen, -1.0, 1.0)))
    altitude = 90.0 - zenith

    # Atmospheric refraction correction (NOAA approximation)
    refr = np.zeros_like(altitude)
    te = np.tan(np.radians(np.clip(altitude, -89.0, 89.0)))
    hi = altitude > 5
    mid = (altitude > -0.575) & ~hi
    lo = altitude <= -0.575
    refr[hi] = 58.1 / te[hi] - 0.07 / te[hi] ** 3 + 0.000086 / te[hi] ** 5
    a = altitude[mid]
    refr[mid] = 1735 + a * (-518.2 + a * (103.4 + a * (-12.79 + a * 0.711)))
    refr[lo] = -20.772 / te[lo]
    refr[altitude > 85] = 0.0
    altitude = altitude + refr / 3600.0

    zen_r = np.radians(zenith)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_az = (np.sin(lat_r) * np.cos(zen_r) - np.sin(decl_r)) / (np.cos(lat_r) * np.sin(zen_r))
    az_raw = np.degrees(np.arccos(np.clip(np.nan_to_num(cos_az), -1.0, 1.0)))
    azimuth = np.where(hour_angle > 0, np.mod(az_raw + 180, 360), np.mod(540 - az_raw, 360))
    return np.asarray(altitude, dtype=float), np.asarray(azimuth, dtype=float)


def solar_position(
    when: datetime | pd.Timestamp | pd.DatetimeIndex, lat: float, lon: float
) -> SunPosition | list[SunPosition]:
    """Return the apparent solar position for one or many timezone-aware datetimes.

    Parameters
    ----------
    when:
        A timezone-aware ``datetime``/``Timestamp`` or a ``DatetimeIndex``.
    lat, lon:
        Observer latitude and longitude in decimal degrees (WGS84).

    Examples
    --------
    >>> from datetime import datetime
    >>> from zoneinfo import ZoneInfo
    >>> p = solar_position(datetime(2026, 6, 21, 12, 20, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    ...                    22.28, 114.16)
    >>> round(p.altitude) >= 88
    True
    """
    alt, az = _solar_arrays(when, lat, lon)
    if isinstance(when, pd.DatetimeIndex):
        return [SunPosition(float(a), float(z)) for a, z in zip(alt, az, strict=True)]
    return SunPosition(float(alt[0]), float(az[0]))
