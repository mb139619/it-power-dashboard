"""EEX EGSI adapter — parse, cache merge, stale-cache fallback. No network."""
import pandas as pd
import pytest

from etl import gas_eex as g

# Shape of a real api.eex-group.com table-data response (values shortened). Note the
# weekend: Sat/Sun/Mon delivery days can share Friday's trade date.
PAYLOAD = {
    "header": ["shortCode", "maturityDate", "tradeDate", "totVolTrdd", "settlPx", "deliveryDay"],
    "data": [
        ["EEX EGSI TTF Day", None, "2026-11-13", None, 91.448, "2026-11-16"],
        ["EEX EGSI TTF Day", None, "2026-11-13", None, 91.546, "2026-11-15"],
        ["EEX EGSI TTF Day", None, "2026-11-13", None, 91.546, "2026-11-14"],
        ["EEX EGSI TTF Day", None, "2026-11-12", None, 91.460, "2026-11-13"],
        ["EEX EGSI TTF Day", None, "2026-11-11", None, None, "2026-11-12"],   # unpriced row
    ],
    "uOM": "MWh", "currency": "EUR",
}


def test_parse_indexes_by_delivery_day_and_drops_unpriced():
    s = g.parse(PAYLOAD)
    assert list(s.index) == list(pd.to_datetime(["2026-11-13", "2026-11-14",
                                                 "2026-11-15", "2026-11-16"]))
    assert s.name == "gas_ttf" and s.index.tz is None
    assert s.loc["2026-11-16"] == pytest.approx(91.448)


def test_parse_reads_columns_by_name():
    reordered = {"header": ["deliveryDay", "settlPx", "tradeDate"],
                 "data": [["2026-11-16", 90.0, "2026-11-13"]]}
    assert g.parse(reordered).iloc[0] == 90.0


def test_parse_rejects_unknown_shape():
    with pytest.raises(ValueError):
        g.parse({"header": ["foo", "bar"], "data": [[1, 2]]})


def test_parse_duplicate_delivery_day_latest_trade_wins():
    p = {"header": ["tradeDate", "settlPx", "deliveryDay"],
         "data": [["2026-11-12", 80.0, "2026-11-13"], ["2026-11-13", 81.0, "2026-11-13"]]}
    assert g.parse(p).loc["2026-11-13"] == 81.0


def test_merge_revision_wins_and_is_logged():
    idx = pd.to_datetime(["2026-11-13", "2026-11-14"])
    cached = pd.Series([90.0, 91.0], index=idx, name="gas_ttf")
    new = pd.Series([91.5, 92.0], index=pd.to_datetime(["2026-11-14", "2026-11-15"]))
    out, log = g.merge(cached, new)
    assert list(out.values) == [90.0, 91.5, 92.0]          # cache never shrinks
    assert len(log) == 1 and "2026-11-14" in log[0]


def test_gas_series_serves_cache_when_eex_fails(tmp_path, monkeypatch):
    path = tmp_path / "gas.parquet"
    g.parse(PAYLOAD).to_frame().to_parquet(path)

    def boom(*a, **k):
        raise ConnectionError("EEX down")
    monkeypatch.setattr(g, "fetch", boom)
    s = g.gas_series("2026-11-01", "2026-11-30", cache_path=path)
    assert len(s) == 4                                      # stale but valid, build survives


def test_gas_series_rejects_implausible_values(tmp_path, monkeypatch):
    path = tmp_path / "gas.parquet"
    good = g.parse(PAYLOAD)
    good.to_frame().to_parquet(path)
    monkeypatch.setattr(g, "fetch", lambda *a, **k: good * 1000)   # unit blunder
    s = g.gas_series("2026-11-01", "2026-11-30", cache_path=path)
    assert s.max() < 200                                    # garbage refused, cache kept
