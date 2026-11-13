from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from shadewalk.sun import solar_position

HK = ZoneInfo("Asia/Hong_Kong")
LAT, LON = 22.302, 114.174  # Hong Kong Observatory


def noon_altitude_expected(decl: float) -> float:
    return 90 - abs(LAT - decl)


def test_winter_solstice_noon_altitude():
    # Solar noon in HK is ~12:25 local in December; declination -23.44 deg.
    p = solar_position(datetime(2026, 12, 21, 12, 25, tzinfo=HK), LAT, LON)
    assert p.altitude == pytest.approx(noon_altitude_expected(-23.44), abs=0.3)
    assert p.azimuth == pytest.approx(180, abs=3)


def test_summer_solstice_sun_nearly_overhead():
    # HK lies just south of the Tropic of Cancer: the noon sun is slightly to the north.
    p = solar_position(datetime(2026, 6, 21, 12, 23, tzinfo=HK), LAT, LON)
    assert p.altitude == pytest.approx(noon_altitude_expected(23.44), abs=0.5)


def test_morning_east_afternoon_west_and_night():
    am = solar_position(datetime(2026, 7, 15, 9, 0, tzinfo=HK), LAT, LON)
    pm = solar_position(datetime(2026, 7, 15, 16, 0, tzinfo=HK), LAT, LON)
    night = solar_position(datetime(2026, 7, 15, 22, 0, tzinfo=HK), LAT, LON)
    assert 45 < am.azimuth < 135 and am.is_up
    assert 225 < pm.azimuth < 315 and pm.is_up
    assert not night.is_up


def test_equinox_sunrise_near_due_east():
    p = solar_position(datetime(2026, 3, 20, 6, 25, tzinfo=HK), LAT, LON)
    assert abs(p.altitude) < 2
    assert p.azimuth == pytest.approx(90, abs=2)


def test_vectorised_matches_scalar():
    idx = pd.date_range("2026-07-15 07:00", periods=5, freq="2h", tz=HK)
    many = solar_position(idx, LAT, LON)
    assert isinstance(many, list) and len(many) == 5
    one = solar_position(idx[2], LAT, LON)
    assert many[2].altitude == pytest.approx(one.altitude)


def test_timezone_equivalence():
    a = solar_position(datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc), LAT, LON)
    b = solar_position(datetime(2026, 7, 15, 15, 0, tzinfo=HK), LAT, LON)
    assert a.altitude == pytest.approx(b.altitude)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        solar_position(datetime(2026, 7, 15, 12), LAT, LON)
