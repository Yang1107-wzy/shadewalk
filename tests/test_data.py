import hashlib
import json

import numpy as np
import pytest

from shadewalk.areas import AREAS, get_area
from shadewalk.data import cache
from shadewalk.data.lst import qa_clear_mask, st_to_celsius
from shadewalk.data.weather import parse_rhrread


class FakeResp:
    def __init__(self, body: bytes):
        self.content = body

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls += 1
        return FakeResp(b'{"ok": true}')


def test_cached_get_downloads_once_and_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADEWALK_CACHE", str(tmp_path))
    s = FakeSession()
    p1 = cache.cached_get("https://example.org/x", {"a": 1}, suffix=".json", session=s)
    p2 = cache.cached_get("https://example.org/x", {"a": 1}, suffix=".json", session=s)
    assert p1 == p2 and s.calls == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    (entry,) = manifest.values()
    assert entry["sha256"] == hashlib.sha256(b'{"ok": true}').hexdigest()
    assert entry["params"] == {"a": 1}


def test_st_to_celsius_and_nodata():
    out = st_to_celsius(np.array([0, 44082]))
    assert np.isnan(out[0])
    assert out[1] == pytest.approx(44082 * 0.00341802 + 149 - 273.15)


def test_qa_mask_bits():
    clear = 0b0000_0000_0100_0000  # bit 6 = clear
    cloud = 1 << 3
    shadow = 1 << 4
    assert qa_clear_mask(np.array([clear, cloud, shadow])).tolist() == [True, False, False]


def test_parse_hko_payload():
    payload = {
        "temperature": {
            "data": [
                {"place": "King's Park", "value": 30},
                {"place": "Hong Kong Observatory", "value": 31},
            ]
        },
        "uvindex": {"data": [{"place": "King's Park", "value": 7}]},
        "humidity": {"data": [{"place": "Hong Kong Observatory", "value": 70}]},
        "updateTime": "2026-07-15T15:02:00+08:00",
    }
    w = parse_rhrread(payload)
    assert (w.temperature_c, w.uv_index, w.humidity_pct) == (31.0, 7.0, 70.0)
    assert parse_rhrread({"uvindex": ""}).uv_index is None


def test_areas_lookup_and_custom_bbox():
    assert get_area("central") is AREAS["central"]
    a = get_area("114.1,22.2,114.2,22.3")
    assert a.bbox == (114.1, 22.2, 114.2, 22.3)
    lat, _lon = a.center
    assert lat == pytest.approx(22.25)
    with pytest.raises(ValueError):
        get_area("nowhere")
    with pytest.raises(ValueError):
        get_area("114.2,22.2,114.1,22.3")


def test_cli_areas_and_bad_area():
    from typer.testing import CliRunner

    from shadewalk.cli import app

    runner = CliRunner()
    res = runner.invoke(app, ["areas"])
    assert res.exit_code == 0 and "mong_kok" in res.output
    res = runner.invoke(app, ["route", "nowhere", "--from", "1,2", "--to", "3,4"])
    assert res.exit_code != 0
    assert "unknown area" in res.output
