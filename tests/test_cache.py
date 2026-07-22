"""Guardrail tests for the incremental raw cache (etl/cache.py).

Lock the behaviours that make the cache correct: the generation MultiIndex survives the
parquet round-trip, later runs download only the tail with a 2-day overlap, ENTSO-E
revisions in the overlap overwrite the cached values, and re-runs are idempotent.
"""
import tempfile
import pathlib

import numpy as np
import pandas as pd

from etl import cache


def _raw(start, end, level=100.0):
    idx = pd.date_range(start, end, freq="15min", tz="Europe/Rome")[:-1]
    h = idx.hour + idx.minute / 60
    gen = pd.DataFrame({
        ("Solar", "Actual Aggregated"): np.clip(4000 * np.sin(np.pi * (h - 7) / 10), 0, None),
        ("Fossil Gas", "Actual Aggregated"): 5000.0,
        ("Hydro Pumped Storage", "Actual Consumption"): np.where((h > 2) & (h < 5), 900.0, 0.0),
    }, index=idx)
    return {"price": pd.Series(level + 5 * np.sin(h), index=idx, name="price_zonal"),
            "load": pd.Series(15000.0, index=idx, name="load"),
            "gen": gen,
            "net_import": pd.Series(2200.0, index=idx, name="net_import")}


def _isolate(monkeypatch, calls):
    monkeypatch.setattr(cache, "RAW_DIR", pathlib.Path(tempfile.mkdtemp()))
    def mock(zone, s, e):
        calls.append(s)
        return _raw(s, e, level=110.0 if len(calls) > 1 else 100.0)  # 2nd call = revision
    monkeypatch.setattr(cache, "fetch_zone", mock)


def test_gen_multiindex_round_trip(monkeypatch):
    _isolate(monkeypatch, [])
    raw = _raw("2026-06-01", "2026-06-05")
    back = cache._split(cache._combine(raw))
    assert isinstance(back["gen"].columns, pd.MultiIndex)
    assert ("Solar", "Actual Aggregated") in back["gen"].columns
    assert ("Hydro Pumped Storage", "Actual Consumption") in back["gen"].columns


def test_incremental_overlap_and_revision(monkeypatch):
    calls = []
    _isolate(monkeypatch, calls)
    S = pd.Timestamp("2026-06-01", tz="Europe/Rome")
    r1 = cache.fetch_zone_cached("Z", S, pd.Timestamp("2026-06-10", tz="Europe/Rome"))
    last1 = r1["price"].index.max()
    r2 = cache.fetch_zone_cached("Z", S, pd.Timestamp("2026-06-13", tz="Europe/Rome"))

    assert calls[1] == last1 - pd.Timedelta(days=2)          # download only the tail + 2d overlap
    ov = r2["price"].loc["2026-06-09 12:00"]                 # inside overlap -> revised (base 110)
    old = r2["price"].loc["2026-06-03 12:00"]               # before overlap -> untouched (base 100)
    assert abs((ov - old) - 10) < 0.01                      # revision won only in the overlap
    assert len(r2["price"]) > len(r1["price"])              # cache grew


def test_idempotent_rerun(monkeypatch):
    _isolate(monkeypatch, [])
    S = pd.Timestamp("2026-06-01", tz="Europe/Rome")
    E = pd.Timestamp("2026-06-10", tz="Europe/Rome")
    n = len(cache.fetch_zone_cached("Z", S, E)["price"])
    again = len(cache.fetch_zone_cached("Z", S, E)["price"])
    assert again == n

