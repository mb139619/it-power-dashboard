"""Configuration for the IT power ETL — window, zones, generation taxonomy, provenance.

Design decisions baked in here (see methodology nodes A and B):
- Window starts 2025-10-01: single 15-min-zonal regime, avoids both 2025 breaks.
- Hydro is split: only run-of-river is must-run; reservoir + pumped stay dispatchable.
- Provenance is a first-class attribute of every output column.
"""
from __future__ import annotations

# --- temporal ----------------------------------------------------------------
TZ = "Europe/Rome"
WINDOW_START = "2025-10-01"          # start of the clean 15-min-zonal regime
RESOLUTION = "PT15M"                  # ISO-8601 duration; MGP MTU since 2025-10-01

# --- bidding zones ------------------------------------------------------------
# Full national set. First runs can use just IT_NORD (clean single-zone balance).
ZONES = ["IT_NORD", "IT_CNOR", "IT_CSUD", "IT_SUD", "IT_CALA", "IT_SICI", "IT_SARD"]

# --- generation taxonomy (ENTSO-E production-type names) ----------------------
# Only run-of-river is subtracted as must-run. This is the split the GB template lacks.
MUST_RUN = {
    "Solar",
    "Wind Onshore",
    "Wind Offshore",
    "Hydro Run-of-river and poundage",
    "Geothermal",
}
# Stay IN the residual (dispatchable / not must-run):
DISPATCHABLE_HYDRO = {"Hydro Water Reservoir", "Hydro Pumped Storage"}
# Pumped-storage *consumption* is demand, handled separately (not negative generation).

# Judgement call (registry #4): Biomass / Waste / Marine treated as dispatchable-ish
# baseload -> left OUT of must-run by default. Flip here if you decide otherwise.

# --- provenance vocabulary ----------------------------------------------------
class P:
    OBSERVED = "observed"            # measured / cleared, taken as-is
    DERIVED = "observed_derived"     # exact deterministic function of observed inputs
    ESTIMATED = "estimated"          # depends on a model/reconstruction (e.g. -eps)
    PROXY = "proxy"                  # a stand-in that is not the true quantity
    ASSUMPTION = "assumption"        # a chosen parameter

# --- source registry (for meta.json) -----------------------------------------
SOURCES = {
    "entsoe": {
        "name": "ENTSO-E Transparency Platform",
        "auth": "free API token (env ENTSOE_TOKEN)",
        "series": ["day_ahead_prices", "actual_load", "generation_by_type",
                   "physical_crossborder_flows"],
        "notes": "IT data submitted by Terna. Load is on the NET (transmission) "
                 "boundary; solar generation is GROSS (includes distributed).",
    },
    # Added in later slices: gme (PUN Index GME weights), snam/psv, eex/eua, terna_portal.
}
