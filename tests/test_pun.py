"""The PUN proxy must be load-weighted: a flat mean misprices the whole continent."""
from etl import build


def _rows(prices_loads):
    return {z: {"price": p, "load": l,
                "profile": [p] * 24, "load_profile": [l] * 24}
            for z, (p, l) in prices_loads.items()}


def test_pun_is_weighted_by_load_not_a_flat_mean():
    # the real evening case: continent at 162, Sicily decoupled at 219
    rows = _rows({"NORD": (162, 26000), "CNOR": (162, 4100), "CSUD": (162, 7700),
                  "SUD": (162, 3100), "CALA": (162, 1100), "SICI": (219, 2700),
                  "SARD": (162, 1200)})
    snap = build.build_snapshot(rows, None, "2026-07-15")
    flat = sum(p for p, _ in [(v["price"], v["load"]) for v in rows.values()]) / len(rows)
    assert snap["pun_proxy"] < flat - 3          # the flat mean overstates by ~5 EUR/MWh
    assert 164 <= snap["pun_proxy"] <= 167       # sits near where consumption is
    # and the continent is no longer shown as trading below the national price
    assert abs(snap["zones"]["NORD"]["spread_vs_pun"]) <= 4
    assert snap["zones"]["SICI"]["spread_vs_pun"] > 45


def test_pun_profile_is_published_for_every_hour():
    rows = _rows({"NORD": (100, 20000), "SICI": (200, 2000)})
    snap = build.build_snapshot(rows, None, "2026-07-15")
    assert len(snap["pun_profile"]) == 24
    assert all(v is not None for v in snap["pun_profile"])
    assert snap["pun_profile"][0] < 120          # weighted toward NORD, not the 150 flat mean


def test_falls_back_to_flat_mean_without_weights():
    rows = {"NORD": {"price": 100, "load": None, "profile": [100] * 24},
            "SICI": {"price": 200, "load": None, "profile": [200] * 24}}
    snap = build.build_snapshot(rows, None, "2026-07-15")
    assert snap["pun_proxy"] == 150              # no weights -> flat mean, not a crash


# --- weights pinned to the price day (no network: the forecast fetch is monkeypatched) ---
import numpy as np
import pandas as pd


def _series(day_from, days, level):
    idx = pd.date_range(day_from, periods=96 * days, freq="15min", tz="Europe/Rome")
    return {"index": [t.isoformat() for t in idx],
            "columns": {"load": {"values": [level(t) for t in idx]}}}


def test_weights_come_from_the_load_forecast_of_the_price_day(monkeypatch):
    day = "2026-11-16"
    fc_idx = pd.date_range(day, periods=96, freq="15min", tz="Europe/Rome")
    monkeypatch.setattr(build, "_fetch_load_forecast",
                        lambda z, s, e: pd.Series(np.where(fc_idx.hour < 12, 10000., 20000.), fc_idx))
    prof, src = build._pun_weights("IT_NORD", _series("2026-11-01", 15, lambda t: 1.0), day)
    assert src == "load_forecast"
    assert prof[0] == 10000 and prof[18] == 20000        # the forecast's own hourly shape


def test_weights_fall_back_to_same_weekday_last_week(monkeypatch):
    def down(*a, **k):
        raise ConnectionError("ENTSO-E down")
    monkeypatch.setattr(build, "_fetch_load_forecast", down)
    # load = 1000 + day-of-month: last Monday (9th) must be used for Monday the 16th,
    # NOT yesterday (15th), which is what the old code picked
    s = _series("2026-11-01", 15, lambda t: 1000.0 + t.day)
    prof, src = build._pun_weights("IT_NORD", s, "2026-11-16")
    assert src == "load_same_weekday_last_week"
    assert prof[10] == 1009


def test_scalar_pun_is_the_profile_at_the_current_hour():
    rows = {"NORD": {"price": 300, "load": 1, "profile": [100] * 18 + [250] * 6,
                     "load_profile": [20000] * 24},
            "SICI": {"price": 300, "load": 1, "profile": [200] * 24, "load_profile": [2000] * 24}}
    snap = build.build_snapshot(rows, None, "2026-11-16", now_hour=19)
    assert snap["pun_proxy"] == round(snap["pun_profile"][19])
