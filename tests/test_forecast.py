"""Per-zone day-ahead outlook: file naming, delta sign, and per-zone failure isolation."""
import pandas as pd
import pytest

from etl import build, config as cfg, forecast as fc


def _net(tz=cfg.TZ, tomorrow_delta=-1500.0):
    """Two days of hourly net load; tomorrow shifted by `tomorrow_delta`."""
    day0 = pd.Timestamp("2026-07-14", tz=tz)
    idx = pd.date_range(day0, periods=48, freq="h", tz=tz)
    base = pd.Series(14000.0 + 3000.0 * (idx.hour / 23.0), index=idx)
    base[base.index.date == (day0 + pd.Timedelta(days=1)).date()] += tomorrow_delta
    return base


def test_publish_forecast_writes_per_zone_file(monkeypatch, tmp_path):
    monkeypatch.setattr(fc, "fetch_net_load_forecast", lambda z, s, e: _net())
    monkeypatch.setattr(build, "DATA_DIR", tmp_path)
    out = build.publish_forecast("IT_SUD")
    assert (tmp_path / "forecast_IT_SUD.json").exists()      # zone-scoped, not a shared file
    assert out["zone"] == "IT_SUD"
    assert len(out["days"]) == 2
    assert out["delta_mean"] < 0                              # tomorrow is softer


def test_forecast_all_skips_failing_zone(monkeypatch, tmp_path):
    def flaky(z, s, e):
        if z == "IT_SICI":
            raise RuntimeError("no wind/solar forecast for this zone")
        return _net()
    monkeypatch.setattr(fc, "fetch_net_load_forecast", flaky)
    monkeypatch.setattr(build, "DATA_DIR", tmp_path)
    out = build.publish_forecast_all(["IT_NORD", "IT_SICI", "IT_SUD"])
    assert set(out) == {"IT_NORD", "IT_SUD"}                  # one zone failing must not sink the rest
    assert not (tmp_path / "forecast_IT_SICI.json").exists()
