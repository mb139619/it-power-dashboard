"""Build orchestrator — fetch, transform, validate, publish.

Produces two artefacts per zone (the SPA's data contract):
  data/series_<zone>.json  — columnar time series, each column provenance-stamped
  data/meta_<zone>.json     — run metadata: sources, window, coverage, guard result

Validation guard (after lptva/gb-power-dashboard's publish gate): a failed refresh leaves
the live JSON untouched rather than shipping a broken axis or a coverage hole.
"""
from __future__ import annotations

import os
import json
import datetime as dt
from pathlib import Path

import pandas as pd

from . import config as cfg
from .fetch import fetch_zone
from .cache import fetch_zone_cached
from . import transform as tf

try:  # load ENTSOE_TOKEN from a .env file if present; export still works without it
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COVERAGE_MIN = 0.98  # refuse to publish below this (guard)


def _write_json(path: Path, obj, **dumps_kwargs) -> None:
    """Atomic write: a crash mid-write can't truncate the live file (write temp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, **dumps_kwargs))
    os.replace(tmp, path)          # atomic on POSIX and Windows


def _iso(index: pd.DatetimeIndex) -> list[str]:
    return [t.isoformat() for t in index]


def assemble(zone: str, start: pd.Timestamp, end: pd.Timestamp,
             rebuild: bool = False) -> tuple[dict, dict]:
    raw = fetch_zone_cached(zone, start, end, rebuild=rebuild)  # incremental raw cache
    idx = raw["load"].index                       # canonical grid = load index
    agg, pumping = tf.split_generation(raw["gen"])
    agg = agg.reindex(idx).interpolate(limit=2)
    mix = tf.generation_mix(agg)                  # six supply buckets for the mix panel
    pumping = pumping.reindex(idx).fillna(0.0)
    net_import = raw["net_import"].reindex(idx).interpolate(limit=2)
    price = raw["price"].reindex(idx)

    # JC#6-rev2: read the residual off the SUPPLY side. No distributed-PV estimate — that
    # quantity is not identifiable from the closure error on free data (6 of 7 zones gave
    # physically impossible shares at similar R^2: misspecification, not noise). See docs.
    resid = tf.residual_load_supply(agg, pumping, net_import).reindex(idx)
    ren_pen = tf.renewable_share(agg, pumping, net_import).reindex(idx)
    eps = tf.closure_error(raw["load"], agg, pumping, net_import).reindex(idx)

    def col(series, unit, provenance, **extra):
        return {"unit": unit, "provenance": provenance,
                "values": [None if pd.isna(v) else round(float(v), 3) for v in series],
                **extra}

    def pick(name):  # generation column if present, else zeros
        return agg[name] if name in agg.columns else pd.Series(0.0, index=idx)

    series = {
        "index": _iso(idx),
        "columns": {
            "price_zonal": col(price, "EUR/MWh", cfg.P.OBSERVED),
            "load": col(raw["load"].reindex(idx), "MW", cfg.P.OBSERVED,
                        note="net (transmission) boundary"),
            "solar_gross": col(pick("Solar"), "MW", cfg.P.OBSERVED,
                               note="includes distributed"),
            "wind": col(pick("Wind Onshore") + pick("Wind Offshore"), "MW", cfg.P.OBSERVED),
            "hydro_ror": col(pick("Hydro Run-of-river and poundage"), "MW", cfg.P.OBSERVED),
            "geothermal": col(pick("Geothermal"), "MW", cfg.P.OBSERVED),
            "gen_thermal": col(mix["thermal"], "MW", cfg.P.OBSERVED,
                               note="fossil fleet — usually the marginal price-setter"),
            "gen_hydro": col(mix["hydro"], "MW", cfg.P.OBSERVED, note="RoR + reservoir + pumped"),
            "gen_other": col(mix["other"], "MW", cfg.P.OBSERVED, note="biomass, waste, nuclear, other"),
            "net_import": col(net_import, "MW", cfg.P.OBSERVED,
                              note="short gaps (<=2 steps) linearly interpolated"),
            "pumping": col(pumping, "MW", cfg.P.OBSERVED, note="demand, not neg. generation"),
            "closure_error": col(eps, "MW", cfg.P.DERIVED,
                                 note="load - (generation - pumping + net import); the part of "
                                      "the balance the free data does not explain (mostly "
                                      "behind-the-meter PV, which we do not estimate — JC#6-rev2)"),
            "residual_load": col(resid, "MW", cfg.P.DERIVED,
                                 note="supply side: dispatchable - pumping + net import; "
                                      "no distributed-PV estimate (JC#6-rev2)"),
            "renewable_penetration": col(ren_pen, "ratio", cfg.P.DERIVED,
                                        note="must-run over total supply — one boundary, "
                                             "matches the generation-mix panel (JC#6-rev2)"),
        },
    }

    coverage = float(price.notna().mean())
    guard = _guard(idx, coverage)
    # The balance does not close: eps is what free ENTSO-E data cannot account for (mostly
    # behind-the-meter PV, plus losses and flow reporting). We publish its size rather than
    # attribute it to distributed PV — an attribution the data cannot support (JC#6-rev2).
    eps_abs = eps.abs()
    balance_gap = {
        "mean_abs_mw": (round(float(eps_abs.mean()), 1) if len(eps_abs.dropna()) else None),
        "p95_abs_mw": (round(float(eps_abs.quantile(0.95)), 1) if len(eps_abs.dropna()) else None),
        "note": "unexplained closure error; the residual is read off the supply side so it does "
                "not depend on attributing this gap",
    }
    meta = {
        "zone": zone,
        "window": [start.date().isoformat(), end.date().isoformat()],
        "resolution": cfg.RESOLUTION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "n_steps": len(idx),
        "coverage_price": round(coverage, 4),
        "sources": cfg.SOURCES,
        "balance_gap": balance_gap,
        "notes": {"interpolation": "Observed generation and net_import series have gaps of "
                                   "<=2 steps linearly interpolated to hold the grid regular"},
        "guard": guard,
    }
    return series, meta


def _guard(idx: pd.DatetimeIndex, coverage: float) -> dict:
    checks = {
        "monotonic": bool(idx.is_monotonic_increasing),
        "unique": bool(idx.is_unique),
        "single_frequency": pd.infer_freq(idx) is not None,
        "coverage_ok": coverage >= COVERAGE_MIN,
    }
    return {"passed": all(checks.values()), "checks": checks}


def publish(zone: str, start=None, end=None, rebuild: bool = False):
    start = start or pd.Timestamp(cfg.WINDOW_START, tz=cfg.TZ)
    end = end or pd.Timestamp.now(tz=cfg.TZ).normalize() + pd.Timedelta(days=1)  # include today (day-ahead known)
    series, meta = assemble(zone, start, end, rebuild=rebuild)

    if not meta["guard"]["passed"]:
        # leave live files intact
        raise RuntimeError(f"[guard] refused to publish {zone}: {meta['guard']['checks']}")

    DATA_DIR.mkdir(exist_ok=True)
    _write_json(DATA_DIR / f"series_{zone}.json", series, separators=(",", ":"))
    _write_json(DATA_DIR / f"meta_{zone}.json", meta, indent=2)
    print(f"[ok] {zone}: {meta['n_steps']} steps, coverage {meta['coverage_price']:.3f}")
    return series, meta


def _latest(series: dict, col: str):
    vals = series["columns"].get(col, {}).get("values", [])
    for v in reversed(vals):
        if v is not None:
            return v
    return None


def _at_now(series: dict, col: str):
    """Value at the current hour (not the last row) — for a day-ahead price the whole day is
    known, so 'latest' would wrongly return the 23:00 price; we want the current hour."""
    idx = pd.to_datetime(series["index"], utc=True).tz_convert(cfg.TZ)
    s = pd.Series(series["columns"].get(col, {}).get("values", []), index=idx).dropna()
    if s.empty:
        return None
    at = s[s.index <= pd.Timestamp.now(tz=cfg.TZ)]
    return float((at if not at.empty else s).iloc[-1])


def publish_internal_flows(days: int = 3) -> dict | None:
    """Write data/internal_flows.json — hourly flow profiles between the Italian zones (Terna).

    Optional by design: without Terna credentials this writes nothing and the map renders as
    before. Prefers TODAY (to match the map's price profile), falling back to the last covered
    day and stamping which one it used.
    """
    from . import internal_flows as ifl
    if not ifl.available():
        print("[internal-flows] no Terna credentials — skipped (map unaffected)")
        return None
    end = pd.Timestamp.now(tz=cfg.TZ).normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=days)
    flows = ifl.fetch_internal_flows(start, end)
    if flows.empty:
        print("[internal-flows] no data returned")
        return None

    today = pd.Timestamp.now(tz=cfg.TZ).date()
    days_avail = sorted(set(flows.index.date))
    covered = lambda d: flows[flows.index.date == d].index.hour.nunique() >= 20
    chosen = today if (today in days_avail and covered(today)) else next(
        (d for d in days_avail[::-1] if covered(d)), days_avail[-1])

    profiles = ifl.hourly_profiles(flows, chosen)
    if not profiles:
        print("[internal-flows] no complete day to publish")
        return None
    out = {
        "date": chosen.isoformat(),
        "links": [{"from": a, "to": b, "profile": profiles.get(f"{a}-{b}")}
                  for a, b in ifl.LINKS if profiles.get(f"{a}-{b}")],
        "unit": "MW",
        "provenance": cfg.P.OBSERVED,
        "source": "Terna physical internal flows (positive = from -> to)",
        "note": "different source from the ENTSO-E power series; the two need not reconcile "
                "to the last MW",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(DATA_DIR / "internal_flows.json", out, separators=(",", ":"))
    print(f"[ok] internal_flows.json — {len(out['links'])} links, profile date {chosen}")
    return out


def publish_flows(zone: str = "IT_NORD", days: int = 3) -> dict | None:
    """Write data/flows.json — net physical flow per northern border (ENTSO-E)."""
    from . import flows as fl
    end = pd.Timestamp.now(tz=cfg.TZ).normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=days)
    df = fl.fetch_border_flows(zone, start, end)
    if df.empty:
        print("[flows] no border data")
        return None
    # one reference instant: the last row where EVERY border is present, so the per-border
    # numbers and the total are coherent (borders publish with different lags)
    full = df.dropna(how="any")
    if full.empty:
        print("[flows] no instant with all borders present")
        return None
    at = full.index[-1]
    row = full.iloc[-1]
    mean24 = df.loc[df.index > at - pd.Timedelta(hours=24)].mean(numeric_only=True)
    borders = [{"code": c, "name": fl.BORDERS[c],
                "net": round(float(row[c])),
                "mean24": (round(float(mean24[c])) if pd.notna(mean24.get(c)) else None)}
               for c in df.columns]
    out = {
        "zone": zone,
        "at": at.isoformat(),
        "borders": borders,
        "total_net": round(float(row.sum())),
        "provenance": cfg.P.OBSERVED,
        "note": "ENTSO-E physical flows (positive = import into the zone); Terna publishes "
                "scheduled commercial exchange, a related but different quantity",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(DATA_DIR / "flows.json", out, separators=(",", ":"))
    tot = out["total_net"]
    detail = " · ".join(f"{b['code']} {b['net']:+}" for b in borders)
    print(f"[ok] flows.json — {zone} net {tot:+} MW at {at:%d/%m %H:%M} ({detail})")
    return out


def publish_forecast(zone: str = "IT_NORD") -> dict | None:
    """Write data/forecast_<zone>.json — today vs tomorrow hourly net-load forecast + delta."""
    from . import forecast as fc
    now = pd.Timestamp.now(tz=cfg.TZ).normalize()
    net = fc.fetch_net_load_forecast(zone, now, now + pd.Timedelta(days=2))
    if net.empty:
        print(f"[forecast] {zone}: no day-ahead forecast available yet")
        return None
    by_day = {}
    for ts, v in net.items():
        by_day.setdefault(ts.date().isoformat(), {})[ts.hour] = v
    dates = sorted(by_day)[:2]                          # today, tomorrow (when published)

    def day_obj(d):
        h = by_day[d]
        prof = [round(h[k]) if k in h else None for k in range(24)]
        vals = [v for v in h.values()]
        return {"date": d, "profile": prof, "peak": round(max(vals)), "mean": round(sum(vals) / len(vals))}

    days = [day_obj(d) for d in dates]
    out = {"zone": zone, "provenance": "forecast",
           "note": "net load = load - (wind + solar) day-ahead forecast",
           "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "days": days}
    if len(days) >= 2:
        out["delta_peak"] = days[1]["peak"] - days[0]["peak"]
        out["delta_mean"] = days[1]["mean"] - days[0]["mean"]
    _write_json(DATA_DIR / f"forecast_{zone}.json", out, separators=(",", ":"))
    msg = f"[ok] forecast_{zone}.json — {len(days)} day(s)"
    if "delta_peak" in out:
        msg += f", tomorrow peak {out['delta_peak']:+} MW vs today"
    print(msg)
    return out


def publish_forecast_all(zones=None) -> dict:
    """Day-ahead outlook for every zone. A zone whose wind/solar forecast ENTSO-E doesn't
    publish is skipped rather than sinking the rest."""
    zones = zones or cfg.ZONES
    out = {}
    for z in zones:
        try:
            r = publish_forecast(z)
            if r:
                out[z] = r
        except Exception as e:
            print(f"[forecast] {z}: skipped ({type(e).__name__}: {str(e)[:60]})")
    print(f"[ok] forecasts: {len(out)}/{len(zones)} zones")
    return out


def publish_storage(country: str = "IT") -> dict | None:
    """Write data/storage.json — seasonal fill-level band + current year (GIE AGSI+)."""
    from . import storage
    df = storage.fetch_storage(country, start="2019-01-01")
    full = df["full"].dropna()
    if full.empty:
        print("[storage] no fill data")
        return None
    cy = int(full.index.max().year)
    hist_years = [y for y in range(cy - 6, cy)]          # up to 6 prior years for the band
    band, cur, prev = storage.seasonal_band(full, hist_years, cy, cy - 1)
    latest = df.dropna(subset=["full"]).iloc[-1]
    today_doy = int(full.index.max().dayofyear)
    hist_avg = float(band["mean"].get(today_doy, float("nan")))
    st = str(latest.get("status", ""))
    out = {
        "latest": {
            "date": full.index.max().date().isoformat(),
            "full": round(float(latest["full"]), 1),
            "gasInStorage": round(float(latest.get("gasInStorage", float("nan"))), 1),
            "trend": round(float(latest.get("trend", float("nan"))), 2),
            "status": st,
            "provenance": storage.STATUS_MAP.get(st, "observed"),
            "vs_hist_avg": (round(float(latest["full"]) - hist_avg, 1)
                            if hist_avg == hist_avg else None),
        },
        "band": [{"doy": int(i), "min": round(r["min"], 1), "max": round(r["max"], 1),
                  "avg": round(r["mean"], 1)} for i, r in band.iterrows()],
        "current": [{"doy": int(i), "full": round(float(v), 1)} for i, v in cur.dropna().items()],
        "prev": ([{"doy": int(i), "full": round(float(v), 1)} for i, v in prev.dropna().items()]
                 if prev is not None else []),
        "hist_years": hist_years,
        "country": country,
        "source": "GIE AGSI+ (status C=confirmed/E=estimated)",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(DATA_DIR / "storage.json", out, separators=(",", ":"))
    print(f"[ok] storage.json — {country} {out['latest']['full']}% full "
          f"({out['latest']['vs_hist_avg']:+} vs {len(hist_years)}y avg), status {st}")
    return out


def _fuels_round(s):
    return [None if pd.isna(v) else round(float(v), 2) for v in s]


def publish_fuels(start=None, end=None) -> dict | None:
    """Write data/fuels.json — daily TTF gas, EUA carbon and marginal-CCGT SRMC (yfinance)."""
    from . import fuels
    start = start or pd.Timestamp(cfg.WINDOW_START, tz=cfg.TZ)
    end = end or pd.Timestamp.now(tz=cfg.TZ).normalize()
    df = fuels.fetch_fuels(start.date(), end.date()).dropna(how="all")
    for w in fuels.sanity(df):
        print(f"[fuels][warn] {w}")
    out = {
        "index": [d.date().isoformat() for d in df.index],
        "columns": {
            "gas_ttf": {"unit": "EUR/MWh_th", "provenance": cfg.P.OBSERVED,
                        "note": "TTF front-month EOD (Yahoo)", "values": _fuels_round(df["gas_ttf"])},
            "eua": {"unit": "EUR/tCO2", "provenance": cfg.P.OBSERVED,
                    "note": "EUA proxy EOD (Yahoo CO2.L)", "values": _fuels_round(df["eua"])},
            "srmc": {"unit": "EUR/MWh_e", "provenance": cfg.P.ASSUMPTION,
                     "note": "(gas + EUA*EF_GAS)/eta — depends on assumed eta, EF",
                     "values": _fuels_round(df["srmc"])},
        },
        "assumptions": {"eta": fuels.ETA, "ef_gas_tco2_per_mwhth": fuels.EF_GAS,
                        "note": "marginal CCGT; per-MWh_e emissions = EF_GAS/eta (~0.40 at eta=0.5)"},
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    DATA_DIR.mkdir(exist_ok=True)
    _write_json(DATA_DIR / "fuels.json", out, separators=(",", ":"))
    if len(df):
        print(f"[ok] fuels.json — {len(df)} days, latest gas {df['gas_ttf'].iloc[-1]:.1f} "
              f"EUR/MWh, EUA {df['eua'].iloc[-1]:.1f} EUR/t, SRMC {df['srmc'].iloc[-1]:.1f} EUR/MWh")
    return out


def _hourly_profile(series: dict, column: str = "price_zonal"):
    """24 hourly means of `column` for the map slider, preferring TODAY (day-ahead prices are
    complete for today); falls back to the last well-covered day. Returns (profile, date).

    Also used for load, which supplies the PUN weights — the day chosen must match the price
    profile's, or prices and weights would come from different days."""
    idx = pd.to_datetime(series["index"], utc=True).tz_convert(cfg.TZ)
    price = pd.Series(series["columns"][column]["values"], index=idx).dropna()
    if price.empty:
        return None, None
    days = set(price.index.date)
    covered = lambda d: price[price.index.date == d].index.hour.nunique() >= 20
    today = pd.Timestamp.now(tz=cfg.TZ).date()
    if today in days and covered(today):
        chosen = today
    else:
        chosen = next((d for d in sorted(days)[::-1] if covered(d)), price.index[-1].date())
    sub = price[price.index.date == chosen]
    hourly = sub.groupby(sub.index.hour).mean()
    fill = float(hourly.mean())
    return [round(float(hourly.get(h, fill)), 1) for h in range(24)], chosen.isoformat()


def build_snapshot(rows: dict, window_end: str | None, profile_date: str | None = None) -> dict:
    """Assemble the zonal snapshot the map reads. PUN here is a PROXY (simple mean of
    zonal prices); the true PUN Index GME is volume-weighted and needs GME data — so the
    spread inherits that proxy status. Carries residual and renewable share per zone too,
    so the map can later be coloured by more than price."""
    # PUN Index GME weights zonal prices by the volume PURCHASED in each zone. We don't have
    # GME volumes, but zonal load is the direct measure of that consumption, so weighting by it
    # is far closer than an unweighted mean: a flat average gives Sicily the same weight as the
    # North, which consumes ~8x more, so any island decoupling pushed our PUN the wrong way
    # (measured: 2-3%, up to 4.5 EUR/MWh). Still a PROXY — GME weights exclude pumping and
    # exports, and bilateral volumes clear differently — but a much better one.
    def _wmean(pairs):
        """pairs = [(price, weight)]; falls back to a flat mean if weights are unusable."""
        ok = [(p, w) for p, w in pairs if p is not None and w is not None and w > 0]
        if not ok:
            vals = [p for p, _ in pairs if p is not None]
            return (sum(vals) / len(vals)) if vals else None
        return sum(p * w for p, w in ok) / sum(w for _, w in ok)

    pun_val = _wmean([(r.get("price"), r.get("load")) for r in rows.values()])
    pun = round(pun_val) if pun_val is not None else None
    # the map slider needs the PUN at every hour, so weight hour by hour too
    pun_profile = None
    profs = {z: r.get("profile") for z, r in rows.items() if r.get("profile")}
    lprofs = {z: r.get("load_profile") for z, r in rows.items() if r.get("load_profile")}
    if profs:
        pun_profile = []
        for h in range(24):
            v = _wmean([(profs[z][h], (lprofs.get(z) or [None] * 24)[h]) for z in profs])
            pun_profile.append(round(v, 1) if v is not None else None)
    zones = {}
    for z, r in rows.items():
        p = r.get("price")
        zones[z] = {
            "price": round(p, 1) if p is not None else None,
            "spread_vs_pun": round(p - pun) if (p is not None and pun is not None) else None,
            "residual": round(r["residual"]) if r.get("residual") is not None else None,
            "renewable_pct": round(r["renewable"] * 100) if r.get("renewable") is not None else None,
            "profile": r.get("profile"),          # 24 hourly zonal prices (last full day)
        }
    # default the slider to the hour with the widest cross-zone spread (most congestion)
    profs = [z["profile"] for z in zones.values() if z.get("profile") and len(z["profile"]) == 24]
    peak_hour = None
    if len(profs) >= 2:
        spreads = [max(p[h] for p in profs) - min(p[h] for p in profs) for h in range(24)]
        peak_hour = int(max(range(24), key=lambda h: spreads[h]))
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "window_end": window_end,
        "profile_date": profile_date,
        "resolution": cfg.RESOLUTION,
        "pun_proxy": pun,
        "pun_profile": pun_profile,
        "peak_hour": peak_hour,
        "pun_note": "zonal prices weighted by zonal load — PROXY for PUN Index GME, which "
                    "weights by MGP purchase volumes (excluding pumping and exports). GME "
                    "publishes the exact index but only via its website, not an API.",
        "provenance": {"price": cfg.P.OBSERVED, "spread_vs_pun": cfg.P.PROXY,
                       "residual": cfg.P.DERIVED, "renewable_pct": cfg.P.DERIVED},
        "zones": zones,
    }


def publish_all(zones, start=None, end=None, rebuild: bool = False) -> dict:
    rows, window_end, profile_date = {}, None, None
    for z in zones:
        try:
            series, meta = publish(z, start, end, rebuild=rebuild)
            window_end = series["index"][-1] if series["index"] else window_end
            prof, pdate = _hourly_profile(series)
            profile_date = pdate or profile_date
            lprof, _ = _hourly_profile(series, "load")
            rows[z] = {"price": _at_now(series, "price_zonal"),
                       "load": _at_now(series, "load"),
                       "load_profile": lprof,
                       "residual": _at_now(series, "residual_load"),
                       "renewable": _at_now(series, "renewable_penetration"),
                       "profile": prof}
        except Exception as e:
            # a failed zone (guard OR network) must not sink the others; keep the type
            # visible so a network error and a real bug stay distinguishable in the log
            print(f"[skip] {z}: {type(e).__name__}: {str(e)[:80]}")
    if not rows:
        # publish-guard for the map: don't overwrite a good snapshot with an empty one
        print("[guard] no zone succeeded — leaving zonal_snapshot.json intact")
        return build_snapshot(rows, window_end, profile_date)
    snap = build_snapshot(rows, window_end, profile_date)
    _write_json(DATA_DIR / "zonal_snapshot.json", snap, indent=2)
    print(f"[ok] zonal_snapshot.json: {len(rows)} zones, PUN proxy {snap['pun_proxy']}")
    try:
        publish_fuels(start, end)
    except Exception as e:
        print(f"[fuels] skipped: {type(e).__name__}: {str(e)[:60]}")
    try:
        publish_storage()
    except Exception as e:
        print(f"[storage] skipped: {type(e).__name__}: {str(e)[:60]}")
    try:
        publish_forecast_all(zones)
    except Exception as e:
        print(f"[forecast] skipped: {type(e).__name__}: {str(e)[:60]}")
    try:
        publish_flows()
    except Exception as e:
        print(f"[flows] skipped: {type(e).__name__}: {str(e)[:60]}")
    try:
        publish_internal_flows()
    except Exception as e:
        print(f"[internal-flows] skipped: {type(e).__name__}: {str(e)[:60]}")
    return snap


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuild = "--rebuild" in sys.argv          # force a full re-download, bypassing the cache
    if "--fuels" in sys.argv:                   # build only the fuel/carbon anchors
        publish_fuels()
    elif "--storage" in sys.argv:               # build only the gas-storage panel
        publish_storage()
    elif "--forecast" in sys.argv:              # build only tomorrow's outlook (all zones)
        publish_forecast_all(args or cfg.ZONES)
    elif "--flows" in sys.argv:                 # build only the cross-border flows
        publish_flows()
    elif "--internal-flows" in sys.argv:        # build only the inter-zonal flows (Terna)
        publish_internal_flows()
    else:
        zones = args or cfg.ZONES               # no zone args -> build every zone + the snapshot
        publish_all(zones, rebuild=rebuild)
