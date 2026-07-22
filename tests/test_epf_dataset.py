"""Leakage is the only bug that makes a backtest a lie — lock it down (no network)."""
import numpy as np
import pandas as pd

from etl import config as cfg, epf_dataset as ed


def _fake(monkeypatch, days=30):
    idx = pd.date_range("2025-10-01", periods=days * 24, freq="h", tz=cfg.TZ)
    h = idx.hour
    price = pd.Series(100 + 30 * np.sin(np.pi * (h - 6) / 12) + idx.dayofyear * 0.1,
                      index=idx, name="price")
    fc = pd.DataFrame({"load_fc": 20000 + 3000 * np.sin(np.pi * (h - 7) / 14),
                       "solar_fc": np.clip(5000 * np.sin(np.pi * (h - 6) / 12), 0, None),
                       "wind_fc": 1200.0}, index=idx)
    fc["net_load_fc"] = fc["load_fc"] - fc["solar_fc"] - fc["wind_fc"]
    monkeypatch.setattr(ed, "fetch_da_forecasts", lambda z, s, e: fc)
    monkeypatch.setattr(ed, "_prices", lambda z, s, e: price)
    return idx, price


def test_price_lags_never_see_the_target_day(monkeypatch):
    """price_lag1d at hour t must be the price 24h earlier — never t itself, never later."""
    idx, price = _fake(monkeypatch)
    df = ed.build_dataset("IT_NORD", idx[0], idx[-1])
    row = df.index[200]
    assert df.loc[row, "price_lag1d"] == price.loc[row - pd.Timedelta(hours=24)]
    assert df.loc[row, "price_lag2d"] == price.loc[row - pd.Timedelta(hours=48)]
    assert df.loc[row, "price_lag7d"] == price.loc[row - pd.Timedelta(days=7)]


def test_rolling_lag_summary_excludes_the_target_day(monkeypatch):
    """price_lag1d_mean must summarise D-1 only — a window that touched D would leak."""
    idx, price = _fake(monkeypatch)
    df = ed.build_dataset("IT_NORD", idx[0], idx[-1])
    row = df.index[300]
    window = price.loc[row - pd.Timedelta(hours=47): row - pd.Timedelta(hours=24)]
    assert abs(df.loc[row, "price_lag1d_mean"] - window.mean()) < 1e-9
    assert df.loc[row, "price_lag1d_mean"] != price.loc[row]


def test_no_actuals_leak_into_features(monkeypatch):
    """Actual load/generation for D do not exist at gate closure: they must not be columns."""
    idx, _ = _fake(monkeypatch)
    df = ed.build_dataset("IT_NORD", idx[0], idx[-1])
    forbidden = {"load", "residual_load", "solar_gross", "wind", "gen_thermal",
                 "renewable_penetration", "net_import", "closure_error"}
    assert not (forbidden & set(df.columns))


def test_features_are_forecasts_not_outturn(monkeypatch):
    idx, _ = _fake(monkeypatch)
    df = ed.build_dataset("IT_NORD", idx[0], idx[-1])
    assert "net_load_fc" in df.columns          # the driver, ex-ante
    assert df.attrs["target"] == "price"
    assert "vintage" in df.attrs["vintage_warning"]
