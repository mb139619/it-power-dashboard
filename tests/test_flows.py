"""Lock the flows contract: one coherent instant, total == sum of borders (no network)."""
import numpy as np
import pandas as pd

from etl import build, config as cfg, flows as fl


def test_flows_single_instant_and_total(monkeypatch, tmp_path):
    idx = pd.date_range("2026-07-14", periods=48, freq="h", tz=cfg.TZ)
    df = pd.DataFrame({"FR": 3400.0, "CH": 3000.0, "AT": 290.0, "SI": 370.0}, index=idx)
    df.loc[df.index[-2:], "CH"] = np.nan          # borders publish with different lags
    df.loc[df.index[-1:], "AT"] = np.nan
    df.loc[df.index[-4:], "SI"] = np.nan
    monkeypatch.setattr(fl, "fetch_border_flows", lambda z, s, e: df)
    monkeypatch.setattr(build, "DATA_DIR", tmp_path)

    out = build.publish_flows("IT_NORD")
    expected = df.dropna(how="any").index[-1]
    assert pd.Timestamp(out["at"]) == expected           # the last row where ALL borders exist
    assert out["total_net"] == sum(b["net"] for b in out["borders"])   # total ties to the parts


def test_flows_excludes_legacy_and_internal_borders():
    assert set(fl.BORDERS) == {"FR", "CH", "AT", "SI"}   # no DE_AT_LU (abolished), no IT_CNOR
