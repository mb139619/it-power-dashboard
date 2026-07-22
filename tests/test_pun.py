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
