"""Lock the SRMC formula and the unit-sanity guard (no network)."""
import pandas as pd
from etl import fuels


def test_srmc_formula():
    # (gas + EUA*EF)/eta ; gas 45, EUA 70, eta .5, EF .20 -> 118
    df = pd.DataFrame({"gas_ttf": [45.0], "eua": [70.0]})
    srmc = (df["gas_ttf"] + df["eua"] * fuels.EF_GAS) / fuels.ETA
    assert abs(srmc.iloc[0] - 118.0) < 1e-9
    assert abs(fuels.EF_GAS / fuels.ETA - 0.40) < 1e-9      # per-MWh_e emissions


def test_sanity_flags_bad_units():
    bad = pd.DataFrame({"gas_ttf": [45.0], "eua": [7000.0], "srmc": [0.0]})
    assert any("EUA" in m for m in fuels.sanity(bad))
    good = pd.DataFrame({"gas_ttf": [45.0], "eua": [70.0], "srmc": [118.0]})
    assert fuels.sanity(good) == []
