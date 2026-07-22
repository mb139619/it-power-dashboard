"""Lock the zonal-snapshot builder: PUN proxy, spreads, provenance, missing-zone handling."""
from etl.build import build_snapshot


def test_snapshot_pun_spreads_and_fields():
    rows = {
        "IT_NORD": {"price": 118.0, "residual": 11860, "renewable": 0.34},
        "IT_SUD":  {"price": 74.0,  "residual": 4200,  "renewable": 0.61},
        "IT_SICI": {"price": 138.0, "residual": 3100,  "renewable": 0.28},
    }
    snap = build_snapshot(rows, "2026-07-08T23:45:00+02:00")
    assert snap["pun_proxy"] == round((118 + 74 + 138) / 3)          # 110
    z = snap["zones"]
    assert z["IT_SICI"]["spread_vs_pun"] == 138 - snap["pun_proxy"]  # +28
    assert z["IT_SUD"]["renewable_pct"] == 61
    assert z["IT_NORD"]["residual"] == 11860
    assert snap["provenance"]["spread_vs_pun"] == "proxy"           # honest: not the real index


def test_snapshot_handles_missing_zone():
    rows = {"IT_NORD": {"price": 100.0, "residual": None, "renewable": None},
            "IT_CALA": {"price": None,  "residual": None, "renewable": None}}
    snap = build_snapshot(rows, None)
    assert snap["pun_proxy"] == 100
    assert snap["zones"]["IT_CALA"]["price"] is None
    assert snap["zones"]["IT_CALA"]["spread_vs_pun"] is None
