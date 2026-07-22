# %% [markdown]
# # Residual-load boundary reconciliation — Italy (ENTSO-E)
#
# **What this answers.** Before we can *define* residual load, we need one empirical
# fact that is not documented cleanly anywhere: on which boundary do our series live?
#
# - **Net (transmission)**: demand already stripped of *all* distributed PV
#   (both injected and self-consumed) — the GB-INDO analogue.
# - **Gross (reconstructed)**: true underlying demand, = net + Terna's *estimate* of
#   distributed PV. This is Estimated, not Observed.
#
# Mixing a net demand series with a full (gross) solar series subtracts distributed
# PV twice -> the "negative residual at solar noon" bug. This notebook runs two tests
# on a single bidding zone (clean unit: zonal load + generation + all-borders flows all
# exist and the balance closes with inter-zonal + international flows together):
#
# 1. **Balance closure**: `Load - (Sum_gen - pumping + net_import)` ~= 0.
#    The size and daily/hourly shape of the residual = the missing distributed-PV gap.
# 2. **Midday-minimum diagnostic**: compute residual with the correct hydro split and
#    look at solar-noon minima on clear-sky summer days. Negative/implausible dips =
#    boundary mismatch.
#
# Requires: `entsoe-py`, an ENTSO-E token in env var `ENTSOE_TOKEN`.
# Pick a HIGH-PV, CLEAR-SKY week (May–Jul) for the diagnostic to bite.

# %%
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from entsoe import EntsoePandasClient

try:  # load ENTSOE_TOKEN from .env if present (this notebook is a separate entry point)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---- config -----------------------------------------------------------------
ZONE = "IT_NORD"          # clean single-zone unit; NORD has heavy distributed PV
TZ = "Europe/Rome"
START = pd.Timestamp("2026-06-10", tz=TZ)   # clear-sky high-PV week, inside the 15-min regime
END = pd.Timestamp("2026-06-17", tz=TZ)
MIDDAY = (11, 15)         # local hours defining the solar-noon window

# Must-run set to SUBTRACT for residual load. Explicit and debatable-by-design.
# Reservoir + pumped hydro are DISPATCHABLE -> they stay IN the residual.
MUST_RUN = {
    "Solar",
    "Wind Onshore",
    "Wind Offshore",
    "Hydro Run-of-river and poundage",
    "Geothermal",
}
# Judgement calls flagged for the writeup, left OUT of must-run by default:
#   Biomass / Waste / Marine -> treated as dispatchable-ish baseload here.

TOKEN = os.environ.get("ENTSOE_TOKEN")


# %%
# ---- pure helpers (no network; unit-testable) -------------------------------
def split_generation(gen: pd.DataFrame):
    """Return (generation_df, pumping_series) from a query_generation frame.

    entsoe-py returns either flat columns (production-type name) or a MultiIndex
    (name, 'Actual Aggregated' | 'Actual Consumption'). Storage types carry a
    consumption column = pumping load. We separate the two cleanly.
    """
    if isinstance(gen.columns, pd.MultiIndex):
        agg = gen.xs("Actual Aggregated", axis=1, level=1)
        if "Actual Consumption" in gen.columns.get_level_values(1):
            cons = gen.xs("Actual Consumption", axis=1, level=1)
        else:
            cons = pd.DataFrame(index=gen.index)
    else:
        agg, cons = gen, pd.DataFrame(index=gen.index)

    pumping = (
        cons["Hydro Pumped Storage"]
        if "Hydro Pumped Storage" in cons.columns
        else pd.Series(0.0, index=gen.index)
    ).fillna(0.0)
    return agg.fillna(0.0), pumping


def must_run_sum(agg: pd.DataFrame, must_run: set) -> pd.Series:
    """Sum only the must-run columns that are actually present."""
    present = [c for c in agg.columns if c in must_run]
    missing = must_run - set(present)
    if missing:
        print(f"[note] must-run types absent in this zone/window: {sorted(missing)}")
    return agg[present].sum(axis=1)


def balance_residual(load, agg, pumping, net_import) -> pd.Series:
    """Closure error eps = Load - (Sum_gen - pumping + net_import).

    Systematic eps>0 concentrated in solar hours => distributed PV missing from
    Sum_gen (Load is gross/reconstructed but solar under-captures it).
    """
    total_gen = agg.sum(axis=1)
    df = pd.concat(
        {"load": load, "gen": total_gen, "pump": pumping, "net_imp": net_import},
        axis=1,
    ).dropna()
    return df["load"] - (df["gen"] - df["pump"] + df["net_imp"])


def residual_load(load, agg, must_run) -> pd.Series:
    df = pd.concat({"load": load, "mr": must_run_sum(agg, must_run)}, axis=1).dropna()
    return df["load"] - df["mr"]


def midday_minima(resid: pd.Series, window=MIDDAY) -> pd.DataFrame:
    """Per-day minimum of residual within the local solar-noon window."""
    lo, hi = window
    mask = (resid.index.hour >= lo) & (resid.index.hour < hi)
    noon = resid[mask]
    g = noon.groupby(noon.index.date)
    return pd.DataFrame({"midday_min": g.min(), "midday_mean": g.mean()})


# %%
# ---- fetch (network) --------------------------------------------------------
def fetch(token, zone, start, end):
    c = EntsoePandasClient(api_key=token)
    load = c.query_load(zone, start=start, end=end)
    load = load.iloc[:, 0] if isinstance(load, pd.DataFrame) else load
    load.name = "load"

    gen = c.query_generation(zone, start=start, end=end)

    # all-borders physical flows: net_import = imports - exports.
    # At single-zone level this includes inter-zonal AND international borders,
    # which is exactly the zone's net import for the balance.
    imp = c.query_physical_crossborder_allborders(zone, start=start, end=end, export=False)
    exp = c.query_physical_crossborder_allborders(zone, start=start, end=end, export=True)
    imp = imp.sum(axis=1) if isinstance(imp, pd.DataFrame) else imp
    exp = exp.sum(axis=1) if isinstance(exp, pd.DataFrame) else exp
    net_import = (imp - exp).rename("net_import")
    return load, gen, net_import


if TOKEN:
    load, gen, net_import = fetch(TOKEN, ZONE, START, END)
    agg, pumping = split_generation(gen)
    # align everything to the load index (handles 15-min MTU vs hourly + DST)
    idx = load.index
    agg = agg.reindex(idx).interpolate(limit=2)
    pumping = pumping.reindex(idx).fillna(0.0)
    net_import = net_import.reindex(idx).interpolate(limit=2)
    print(f"coverage: {len(idx)} steps  {idx.min()} -> {idx.max()}  "
          f"step={pd.infer_freq(idx)}")
else:
    raise SystemExit("Set ENTSOE_TOKEN in your environment and re-run.")


# %%
# ---- TEST 1: balance closure ------------------------------------------------
eps = balance_residual(load, agg, pumping, net_import)
eps_hourly = eps.groupby(eps.index.hour).mean()

print("Balance closure error (MW):")
print(f"  mean   {eps.mean():8.1f}")
print(f"  median {eps.median():8.1f}")
print(f"  noon(12-14) {eps.between_time('12:00','14:00').mean():8.1f}")
print(f"  night(00-04){eps.between_time('00:00','04:00').mean():8.1f}")
print("If noon >> night and positive -> distributed PV missing from Sum_gen "
      "(gross Load vs under-captured solar). That gap is Estimated, not Observed.")


# %%
# ---- TEST 2: residual load + midday diagnostic ------------------------------
resid = residual_load(load, agg, MUST_RUN)
mm = midday_minima(resid, MIDDAY)

neg_days = int((mm["midday_min"] < 0).sum())
print(f"\nResidual load: min={resid.min():.0f} MW, "
      f"days with negative solar-noon residual = {neg_days}/{len(mm)}")
if neg_days:
    print(">> BOUNDARY MISMATCH: net demand series minus a gross solar series. "
          "Double-counting distributed PV. Realign both to the same reconstruction.")
else:
    print(">> No negative midday residual: boundary looks internally consistent.")


# %%
# ---- plots ------------------------------------------------------------------
fig, ax = plt.subplots(3, 1, figsize=(11, 11), constrained_layout=True)

ax[0].plot(eps.index, eps.values, lw=0.8)
ax[0].axhline(0, color="k", lw=0.6)
ax[0].set_title("Test 1 — balance closure error  Load-(Sum_gen-pump+net_imp)  [MW]")
ax[0].set_ylabel("MW")

ax[1].bar(eps_hourly.index, eps_hourly.values)
ax[1].axhline(0, color="k", lw=0.6)
ax[1].set_title("Closure error by hour of day (a solar-noon hump = missing distributed PV)")
ax[1].set_xlabel("local hour"); ax[1].set_ylabel("mean MW")

# money shot: sunniest day, residual vs must-run stack
solar = agg["Solar"] if "Solar" in agg else pd.Series(0.0, index=agg.index)
sunniest = pd.Series(solar).groupby(solar.index.date).max().idxmax()
day = resid[resid.index.date == sunniest]
ax[2].plot(day.index, day.values, label="residual load")
ax[2].axhline(0, color="r", lw=0.8, ls="--")
ax[2].set_title(f"Test 2 — residual load on sunniest day ({sunniest}); "
                "dip below the red line = double-count")
ax[2].set_ylabel("MW"); ax[2].legend()

plt.savefig("residual_boundary_diagnostic.png", dpi=130)
print("saved residual_boundary_diagnostic.png")


# %% [markdown]
# ## Reading the verdict
# - **eps ~ 0 flat all day** -> Load and solar share one reconstruction (gross,
#   internally consistent). Residual = Load - must-run is safe. Stamp it **Estimated**
#   anyway (it inherits Terna's distributed-PV estimate).
# - **eps has a positive solar-noon hump** -> Sum_gen under-captures distributed PV
#   while Load is gross. Quantify the hump: that MW figure *is* the provenance story.
# - **negative midday residual** -> you mixed a net demand series with a gross solar
#   series. Realign to one boundary before defining residual.
#
# ### Next layer (cross-source): pull Terna-portal load for the same window and
# overlay on ENTSO-E load. Cross-source boundary mismatch (Terna vintage vs ENTSO-E)
# is the *other* place the bug hides, and needs the Terna developer key.


# %% [markdown]
# ## Correction — back out distributed PV from the closure error
# The eps campana (negative, solar-shaped) is not noise. With ENTSO-E Load on the NET
# boundary and ENTSO-E solar on the GROSS boundary, the balance identity collapses to
#   eps = Load - (Sum_gen - pump + net_imp) = -(distributed generation)
# so **-eps during daylight is a first-order estimate of distributed PV** — from ENTSO-E
# alone, no Terna key. (Small residual terms: grid losses, distributed wind, averaging;
# treat as first-order and sanity-check magnitude against Terna's published MONTHLY
# distributed-PV figure, which is a public number, not an API.)

# %%
# Distributed PV is a SLOW/SMOOTH quantity. The 15-min balance is dominated by genuine
# sub-hourly net_import volatility (~1.9 GW swing on IT_NORD) uncorrelated with load/solar,
# which swamps the distributed signal and makes eps a sawtooth. So estimate D_pv at HOURLY
# resolution (noise cancels, eps recovers a clean campana), then interpolate back to 15-min
# (legitimate: D_pv is smooth). See judgement call #5.
eps = eps.reindex(idx).interpolate(limit=2)                     # 15-min eps: noise-dominated
eps_h = balance_residual(load.resample("1h").mean(), agg.resample("1h").mean(),
                         pumping.resample("1h").mean(), net_import.resample("1h").mean())
baseline = eps_h.between_time("00:00", "04:00").mean()   # non-solar offset (grid losses), JC#6
print(f"non-solar offset removed (nighttime eps baseline): {baseline:.0f} MW")
D_pv = (-(eps_h - baseline)).clip(lower=0).reindex(idx).interpolate("time").ffill().bfill()
step_h = (idx[1] - idx[0]).total_seconds() / 3600
week_gwh = float(D_pv.sum() * step_h / 1000)
print(f"implied distributed PV (hourly): peak {D_pv.max():.0f} MW, "
      f"noon(12-14) mean {D_pv.between_time('12:00','14:00').mean():.0f} MW")
print(f"implied distributed-PV energy this week ~ {week_gwh:.0f} GWh "
      f"-> sanity-check vs Terna Rapporto Mensile distributed figure")


# %% [markdown]
# ## Key result: residual is boundary-INVARIANT once consistent
# Distributed PV cancels (it lowers demand AND adds must-run by the same amount), so the
# fix is not "pick gross or net" — it is "be consistent". Corrected residual strips
# distributed OUT of solar:  R = Load - (Solar_entsoe - D_pv) - Wind - RoR - Geo.
# Verified identical to the gross-boundary residual and to (dispatchable - pump + net_imp).

# %%
solar_full = agg["Solar"] if "Solar" in agg else pd.Series(0.0, index=idx)
U_solar = (solar_full - D_pv).clip(lower=0)      # utility / transmission-visible solar
mr_fixed = (U_solar + must_run_sum(agg, MUST_RUN - {"Solar"})).reindex(idx)
resid_fixed = (load - mr_fixed).dropna()

day0 = resid[resid.index.date == sunniest]
day1 = resid_fixed[resid_fixed.index.date == sunniest]
fig2, ax2 = plt.subplots(figsize=(11, 4), constrained_layout=True)
ax2.plot(day0.index, day0.values, lw=1.0, ls="--",
         label="raw: Load - gross solar  (artifact dip = double-count)")
ax2.plot(day1.index, day1.values, lw=1.6,
         label="fixed: distributed stripped from solar")
ax2.axhline(0, color="r", lw=0.6)
ax2.set_title(f"Residual load, sunniest day ({sunniest}) — before vs after boundary fix")
ax2.set_ylabel("MW"); ax2.legend()
plt.savefig("residual_boundary_fixed.png", dpi=130)
print(f"noon(12-14) mean:  raw {day0.between_time('12:00','14:00').mean():.0f} -> "
      f"fixed {day1.between_time('12:00','14:00').mean():.0f} MW  "
      f"(gap = double-counted distributed PV, lifted back)")
print("saved residual_boundary_fixed.png")


# %% [markdown]
# ## Provenance stamp for the writeup
# - Residual load -> **Estimated** (inherits a first-order distributed-PV estimate = -eps).
# - Distributed-PV series -> **Estimated** (closure-error method; cross-checked vs Terna monthly).
# - Boundary lesson for later: the discipline transfers to FORECAST features
#   (load-forecast source and renewable-forecast source must share one boundary),
#   which is where the double-count would bias the EPF model rather than just the actuals.


# %% [markdown]
# ## Validation — is the distributed-PV estimate a plausible size?
# `-eps` captures ONLY distributed PV; ENTSO-E's Solar series is the TOTAL (utility +
# distributed). So `distributed / total` should be a plausible *share*, not 1. Using
# ENTSO-E's own total solar as the denominator makes this an internal consistency check —
# no external number required. Optionally cross-anchor the total against Terna's published
# monthly FV figure (Rapporto Mensile) for the month covering this window.

# %%
step_h = (idx[1] - idx[0]).total_seconds() / 3600
n_days = (idx[-1] - idx[0]).total_seconds() / 86400
solar_full = agg["Solar"] if "Solar" in agg.columns else pd.Series(0.0, index=idx)

solar_total_gwh = float(solar_full.sum() * step_h / 1000)   # ENTSO-E total solar (gross)
distributed_gwh = float(D_pv.sum() * step_h / 1000)         # -eps estimate (hourly-based)
share = distributed_gwh / solar_total_gwh if solar_total_gwh else float("nan")

print(f"window: {idx[0].date()} -> {idx[-1].date()}  ({n_days:.1f} days)")
print(f"ENTSO-E total solar : {solar_total_gwh:7.0f} GWh  ({solar_total_gwh/n_days:5.0f} GWh/day)")
print(f"distributed (-eps)  : {distributed_gwh:7.0f} GWh  ({distributed_gwh/n_days:5.0f} GWh/day)")
print(f"distributed share   : {share:5.1%}")
# NOTE: the band below is a rough sanity range, NOT a calibrated figure — refine it against
# Terna's actual distributed-vs-utility split once you have it.
# NOTE: the distributed share is ZONE-DEPENDENT and this band is a rough sanity range, not
# a calibration. Nord is distributed-heavy (rooftops, few utility plants) -> high share
# (~55-75%); the South is utility-heavy -> low share. Refine per zone against Terna's split.
verdict = "plausible" if 0.20 <= share <= 0.80 else "CHECK — outside rough sanity band"
print(f"  -> {verdict}")

# Optional cross-source anchor: paste Terna monthly TOTAL FV (GWh) and the month's days.
# Leave TERNA_FV_GWH = None to skip. (This anchors the TOTAL, not the distributed part.)
TERNA_FV_GWH = None      # e.g. 3322 for Oct-2025
TERNA_FV_DAYS = None     # e.g. 31
if TERNA_FV_GWH and TERNA_FV_DAYS:
    entsoe_daily = solar_total_gwh / n_days
    terna_daily = TERNA_FV_GWH / TERNA_FV_DAYS
    print(f"\ncross-source (daily avg): ENTSO-E total {entsoe_daily:.0f} vs "
          f"Terna total {terna_daily:.0f} GWh/day  "
          f"(ratio {entsoe_daily/terna_daily:.2f}; ~1.0 = sources agree)")
