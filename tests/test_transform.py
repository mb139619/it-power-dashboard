"""Guardrail tests for the transform core — the figures that must never regress.

Same spirit as lptva/gb-power-dashboard's pinned-figure tests: these lock the verified
identities (node A) so a future refactor can't silently reintroduce the
double-count bug.
"""
import numpy as np
import pandas as pd

from etl import transform as tf


def _synthetic():
    idx = pd.date_range("2025-10-01", "2025-10-02 23:45", freq="15min", tz="Europe/Rome")
    h = idx.hour + idx.minute / 60
    U_s = np.clip(4000 * np.sin(np.pi * (h - 6) / 12), 0, None)   # utility solar
    D_s = np.clip(3500 * np.sin(np.pi * (h - 6) / 12), 0, None)   # distributed solar
    solar = U_s + D_s                                             # ENTSO-E gross
    wind = np.full(len(idx), 1500.0)
    ror = np.full(len(idx), 2000.0)
    geo = np.full(len(idx), 900.0)
    gas = 6000 + 2000 * np.sin(np.pi * (h - 8) / 16)
    reservoir = np.full(len(idx), 1500.0)
    pump_con = np.where((h > 2) & (h < 5), 1200.0, 0.0)
    net_imp = pd.Series(2500.0, index=idx)

    agg = pd.DataFrame({
        "Solar": solar, "Wind Onshore": wind, "Hydro Run-of-river and poundage": ror,
        "Geothermal": geo, "Fossil Gas": gas, "Hydro Water Reservoir": reservoir,
        "Hydro Pumped Storage": np.zeros(len(idx)),
    }, index=idx)
    agg.columns = pd.MultiIndex.from_product([agg.columns, ["Actual Aggregated"]])
    con = pd.DataFrame({("Hydro Pumped Storage", "Actual Consumption"): pump_con}, index=idx)
    gen = pd.concat([agg, con], axis=1)

    total_gen = gen.xs("Actual Aggregated", axis=1, level=1).sum(axis=1)
    T = total_gen - pd.Series(pump_con, index=idx) + net_imp   # true demand (balance)
    load = (T - D_s).rename("load")                            # ENTSO-E net load
    return idx, gen, load, net_imp, pd.Series(D_s, index=idx)


def test_split_generation_pumping():
    idx, gen, *_ = _synthetic()
    agg, pumping = tf.split_generation(gen)
    assert "Solar" in agg.columns
    assert (pumping > 0).any() and pumping.max() == 1200.0


def test_eps_equals_minus_distributed():
    idx, gen, load, net_imp, D_s = _synthetic()
    agg, pumping = tf.split_generation(gen)
    eps = tf.closure_error(load, agg, pumping, net_imp).reindex(idx)
    assert np.allclose(eps.values, -D_s.values, atol=1e-6)




def test_generation_mix_buckets():
    idx = pd.date_range("2026-06-01", periods=2, freq="h", tz="Europe/Rome")
    agg = pd.DataFrame({"Fossil Gas": [5000., 4000], "Fossil Oil": [200., 100],
                        "Solar": [3000., 0], "Wind Onshore": [1500., 1800],
                        "Hydro Water Reservoir": [900., 800], "Geothermal": [700., 700],
                        "Biomass": [400., 400], "Nuclear": [0., 0]}, index=idx)
    mix = tf.generation_mix(agg)
    assert list(mix.columns) == ["thermal", "solar", "wind", "hydro", "geothermal", "other"]
    assert mix["thermal"].iloc[0] == 5200.        # gas + oil
    assert mix["other"].iloc[0] == 400.           # biomass (+ nuclear 0)
    assert mix["solar"].iloc[1] == 0.




def test_supply_side_residual_equals_demand_side_when_the_balance_closes():
    """The theoretical link that licenses the switch (JC#6-rev2).

    R_supply = dispatchable - pumping + net_import must equal the textbook demand-side
    R = Load - must_run whenever the balance closes — which the fixture guarantees. The point
    of the supply-side form is that it needs no distributed-PV estimate to get there.
    """
    idx, gen, load, net_imp, D_s = _synthetic()
    agg, pumping = tf.split_generation(gen)

    r_supply = tf.residual_load_supply(agg, pumping, net_imp).reindex(idx)

    # demand side, computed here with the fixture's TRUE distributed PV (never available live)
    util_solar = agg["Solar"] - D_s
    must_run = util_solar + agg["Wind Onshore"] + agg["Hydro Run-of-river and poundage"] + agg["Geothermal"]
    r_demand = (load - must_run).reindex(idx)

    assert np.allclose(r_supply.values, r_demand.values, atol=1e-6)


def test_supply_side_residual_uses_no_estimate():
    """Only observed columns: dispatchable output, pumping, flows. No k, no D_pv."""
    idx, gen, load, net_imp, _ = _synthetic()
    agg, pumping = tf.split_generation(gen)
    r = tf.residual_load_supply(agg, pumping, net_imp).reindex(idx)
    expected = (agg["Fossil Gas"] + agg["Hydro Water Reservoir"] - pumping + net_imp).reindex(idx)
    assert np.allclose(r.values, expected.values, atol=1e-6)


def test_renewable_share_is_boundary_consistent():
    """Must-run over local generation: both sides gross, so no net-load/gross-solar mixing."""
    idx = pd.date_range("2026-06-01", periods=2, freq="h", tz="Europe/Rome")
    agg = pd.DataFrame({"Solar": [1000., 1000], "Fossil Gas": [1000., 1000]}, index=idx)
    pumping = pd.Series([0., 0], index=idx)
    net_imp = pd.Series([0., 0], index=idx)
    rs = tf.renewable_share(agg, pumping, net_imp)
    assert np.allclose(rs.values, 0.5)          # 1000 solar of 2000 supplied


def test_renewable_share_bounded_in_exporting_zone():
    """IT_SUD-like hour: 3 GW wind + 0.9 GW gas, 3.9 GW exported. Over supply this read ~900%;
    over local generation it must be the physical 77%."""
    idx = pd.date_range("2026-11-16", periods=1, freq="h", tz="Europe/Rome")
    agg = pd.DataFrame({"Wind Onshore": [3000.], "Fossil Gas": [900.]}, index=idx)
    pumping = pd.Series([0.], index=idx)
    net_imp = pd.Series([-3890.], index=idx)
    rs = tf.renewable_share(agg, pumping, net_imp)
    assert 0 <= rs.iloc[0] <= 1
    assert np.isclose(rs.iloc[0], 3000 / 3900)


def test_renewable_share_no_inf_on_zero_supply():
    idx = pd.date_range("2026-06-01", periods=2, freq="h", tz="Europe/Rome")
    agg = pd.DataFrame({"Solar": [0., 500], "Fossil Gas": [0., 500]}, index=idx)
    pumping = pd.Series([0., 0], index=idx)
    net_imp = pd.Series([0., 0], index=idx)
    rs = tf.renewable_share(agg, pumping, net_imp)
    assert not np.isinf(rs).any()
    assert pd.isna(rs.iloc[0])                  # nothing supplied -> undefined, not inf
