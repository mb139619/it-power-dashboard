"""Transform layer — the verified analytics core.

These functions are the refactored, tested logic from the boundary-reconciliation
work (nodes A). The key facts they encode:
  - eps = Load - (Sum_gen - pumping + net_import) = -(distributed generation)
  - so distributed PV ~= max(-eps, 0)  (first-order, ENTSO-E only)
  - residual is boundary-invariant once consistent; we compute it on the
    market-facing boundary by stripping distributed PV out of solar.
Anything that touches the distributed-PV estimate is Estimated, not Observed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import MUST_RUN


def split_generation(gen: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Separate aggregated generation from storage consumption (pumping).

    entsoe-py returns flat columns (type name) or MultiIndex
    (name, 'Actual Aggregated' | 'Actual Consumption'). Pumping = the consumption
    side of Hydro Pumped Storage, which is demand, not negative generation.
    """
    if isinstance(gen.columns, pd.MultiIndex):
        agg = gen.xs("Actual Aggregated", axis=1, level=1)
        levels = gen.columns.get_level_values(1)
        cons = gen.xs("Actual Consumption", axis=1, level=1) if "Actual Consumption" in levels \
            else pd.DataFrame(index=gen.index)
    else:
        agg, cons = gen, pd.DataFrame(index=gen.index)

    pumping = (
        cons["Hydro Pumped Storage"] if "Hydro Pumped Storage" in cons.columns
        else pd.Series(0.0, index=gen.index)
    ).fillna(0.0)
    return agg.fillna(0.0), pumping


def closure_error(load: pd.Series, agg: pd.DataFrame,
                  pumping: pd.Series, net_import: pd.Series) -> pd.Series:
    """eps = Load - (Sum_gen - pumping + net_import).

    With ENTSO-E's net Load and gross Solar, eps ~= -(distributed generation):
    a negative, solar-shaped campana. See node A.4.
    """
    df = pd.concat(
        {"load": load, "gen": agg.sum(axis=1), "pump": pumping, "imp": net_import},
        axis=1,
    ).dropna()
    return df["load"] - (df["gen"] - df["pump"] + df["imp"])




def total_supply(agg: pd.DataFrame, pumping: pd.Series, net_import: pd.Series) -> pd.Series:
    """Everything the transmission grid was served with: generation - pumping + net import.
    OBSERVED_DERIVED (exact function of observed inputs)."""
    return agg.sum(axis=1).sub(pumping, fill_value=0.0).add(net_import, fill_value=0.0)


def residual_load_supply(agg: pd.DataFrame, pumping: pd.Series, net_import: pd.Series,
                         must_run: set[str] = MUST_RUN) -> pd.Series:
    """Residual demand read from the SUPPLY side — the merit-order quantity, no estimate:

        R = dispatchable - pumping + net_import

    i.e. what the dispatchable fleet plus imports actually had to deliver once must-run
    renewables had taken their place. This is the same economic quantity as the demand-side
    definition (Load - must_run) — the balance identity makes them equal when it closes — but
    it uses only OBSERVED columns, so it needs no distributed-PV estimate (JC#6-rev2).

    Why the switch: the demand-side form mixes ENTSO-E's NET load with GROSS solar, so it needs
    D_pv to be boundary-consistent, and D_pv turned out not to be identifiable from the closure
    error on free data (6 of 7 zones returned physically impossible shares at similar R^2 —
    misspecification, not noise; see docs JC#6-rev2). Reading the residual off the supply side
    sidesteps the estimate entirely.

    Cost, declared: the two definitions differ by the closure error eps, which does not vanish
    (~1-3 GW on IT_NORD). That disagreement is now an explicit, published gap instead of being
    silently absorbed into "distributed PV". OBSERVED_DERIVED.
    """
    disp = [c for c in agg.columns if c not in must_run]
    return (agg[disp].sum(axis=1).sub(pumping, fill_value=0.0)
            .add(net_import, fill_value=0.0)).dropna()


def renewable_share(agg: pd.DataFrame, pumping: pd.Series, net_import: pd.Series,
                    must_run: set[str] = MUST_RUN) -> pd.Series:
    """Must-run renewables as a share of the zone's LOCAL GENERATION — one boundary, no estimate.

    Both sides are gross generation, so no mixing of ENTSO-E's net load with gross solar (the
    node-A error), and the KPI means the same thing as the generation-mix panel, which also
    divides by generation.

    Why not total supply (gen - pumping + net import): in an exporting zone (SUD, CALA, SARD)
    the export is as large as local output, the denominator collapses towards 0 and the share
    read 600-900% — over 100% in half of SUD's slots. Bounded in [0, 1] here by construction.
    pumping / net_import are kept in the signature for call-site stability. OBSERVED_DERIVED.
    """
    present = [c for c in agg.columns if c in must_run]
    if not present:
        return pd.Series(0.0, index=agg.index)
    gen = agg.sum(axis=1)
    return (agg[present].sum(axis=1) / gen.where(gen > 0)).clip(lower=0, upper=1)


# --- generation mix: group ENTSO-E types into readable buckets (supply side of the price) ---
GEN_BUCKETS = {
    "thermal":    ["Fossil Gas", "Fossil Oil", "Fossil Hard coal", "Fossil Brown coal/Lignite",
                   "Fossil Coal-derived gas", "Fossil Peat", "Other fossil"],
    "solar":      ["Solar"],
    "wind":       ["Wind Onshore", "Wind Offshore"],
    "hydro":      ["Hydro Run-of-river and poundage", "Hydro Water Reservoir", "Hydro Pumped Storage"],
    "geothermal": ["Geothermal"],
    "other":      ["Biomass", "Waste", "Other renewable", "Other", "Nuclear", "Marine"],
}


def generation_mix(agg: pd.DataFrame) -> pd.DataFrame:
    """Collapse the ENTSO-E generation-by-type frame into six buckets (thermal, solar, wind,
    hydro, geothermal, other). Thermal is the fossil fleet — usually the marginal price-setter."""
    out = {}
    for bucket, types in GEN_BUCKETS.items():
        cols = [t for t in types if t in agg.columns]
        out[bucket] = agg[cols].sum(axis=1) if cols else pd.Series(0.0, index=agg.index)
    return pd.DataFrame(out, index=agg.index)
