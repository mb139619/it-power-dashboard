"""EPF dataset — a leakage-safe feature matrix from real data, for the epf-toolkit.

The toolkit already has the models, the rolling-origin backtest and the metrics. What it needs
is a dataset that is honest about *what was knowable when*. That is this module's only job.

THE DISCIPLINE
--------------
The target is the MGP day-ahead price for delivery day D, hour h. The decision point is gate
closure at 12:00 on D-1: a feature may only enter if it existed before that instant.

  allowed
    * day-ahead forecasts for D (load, wind, solar) — published ahead of gate closure, that is
      their purpose. From them: NET LOAD = load_fc - wind_fc - solar_fc, the price-relevant
      driver (residual demand, not total demand).
    * prices for D-1 and earlier. At 12:00 on D-1 the D-1 prices are known (cleared on D-2).
    * fuel settlements up to D-2. Gas and EUA settle end-of-day, so D-1's settlement is NOT
      final at noon on D-1 — we use D-2 and take the one-day cost of being safe.
    * the calendar, which is known forever.

  forbidden (and easy to get wrong)
    * actual load / actual generation for D — the classic leak. These are the columns the
      dashboard shows, and they do not exist at gate closure.
    * price for D itself in any lagged form other than D-1 and older.

THE CAVEAT THAT MATTERS (declared, not hidden)
---------------------------------------------
ENTSO-E serves the *current* version of a series: data providers overwrite earlier submissions
(Reg. 543/2013). So a day-ahead forecast fetched today for a past day may be a REVISED vintage,
not the one that was on the screen at gate closure. If forecasts were revised toward the
outturn, a backtest built this way is OPTIMISTIC — the model sees a better future than you
could have bought.

We cannot reconstruct vintages from the API. What we can do is stop the bleeding going forward:
`snapshot_forecast_vintage()` appends today's forecast, as published now, to a growing archive.
Give it a few months and the backtest can be re-run on true point-in-time data. Until then,
read the metrics as an upper bound on skill, and say so.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd

from . import config as cfg

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EPF_DIR = DATA_DIR / "epf"
VINTAGE_DIR = EPF_DIR / "vintages"

# Italian national holidays across the project window. A static list beats a dependency here:
# it is auditable, and the window is fixed by design (post 2025-10-01 15-min MGP regime).
IT_HOLIDAYS = {
    "2025-11-01", "2025-12-08", "2025-12-25", "2025-12-26",
    "2026-01-01", "2026-01-06", "2026-04-05", "2026-04-06",   # Easter Sun/Mon 2026
    "2026-04-25", "2026-05-01", "2026-06-02", "2026-08-15",
    "2026-11-01", "2026-12-08", "2026-12-25", "2026-12-26",
}


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    from entsoe import EntsoePandasClient
    return EntsoePandasClient(api_key=os.environ["ENTSOE_TOKEN"])


def fetch_da_forecasts(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Day-ahead forecasts (process A01) of load, wind and solar -> the net-load driver.

    Returns hourly load_fc / wind_fc / solar_fc / net_load_fc, all in MW.
    """
    c = _client()
    load = c.query_load_forecast(zone, start=start, end=end)
    load_s = load.iloc[:, 0] if hasattr(load, "columns") else load
    ws = c.query_wind_and_solar_forecast(zone, start=start, end=end)
    solar = ws["Solar"] if "Solar" in ws.columns else pd.Series(0.0, index=ws.index)
    wind_cols = [x for x in ws.columns if "Wind" in x]
    wind = ws[wind_cols].sum(axis=1) if wind_cols else pd.Series(0.0, index=ws.index)
    df = pd.concat({"load_fc": load_s, "solar_fc": solar, "wind_fc": wind}, axis=1)
    df = df.resample("h").mean()
    df["net_load_fc"] = df["load_fc"] - df["solar_fc"] - df["wind_fc"]
    return df.dropna(how="all")


def _prices(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Hourly day-ahead price. Uses the raw cache when present (no re-download)."""
    p = DATA_DIR / "raw" / f"{zone}.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        col = "price_zonal" if "price_zonal" in df.columns else df.columns[0]
        s = df[col]
    else:
        from .fetch import fetch_zone
        s = fetch_zone(zone, start, end)["price"]
    s.index = pd.to_datetime(s.index)
    return s.resample("h").mean().loc[start:end]


def build_dataset(zone: str = "IT_NORD", start=None, end=None) -> pd.DataFrame:
    """Assemble the leakage-safe matrix. One row per delivery hour; target = that hour's price."""
    start = start or pd.Timestamp(cfg.WINDOW_START, tz=cfg.TZ)
    end = end or pd.Timestamp.now(tz=cfg.TZ).normalize()

    fc = fetch_da_forecasts(zone, start, end)
    price = _prices(zone, start, end).rename("price")
    df = pd.concat([price, fc], axis=1).dropna(subset=["price"])

    # --- price lags: only D-1 and older are known at noon on D-1 ---
    for lag_d in (1, 2, 7):
        df[f"price_lag{lag_d}d"] = df["price"].shift(24 * lag_d)
    # the previous day's shape, summarised — cheap and strong in EPF practice
    df["price_lag1d_mean"] = df["price"].shift(24).rolling(24).mean()
    df["price_lag1d_max"] = df["price"].shift(24).rolling(24).max()

    # --- fuels: use the D-2 settlement (D-1 has not settled at gate closure) ---
    try:
        from . import fuels as fu
        f = fu.fetch_fuels(start.date(), end.date())
        f.index = pd.to_datetime(f.index)
        daily = f[["gas_ttf", "eua", "srmc"]].shift(2)          # D-2, in delivery-day terms
        daily.index = daily.index.tz_localize(cfg.TZ) if daily.index.tz is None else daily.index
        df = df.join(daily.reindex(df.index, method="ffill"))
    except Exception as e:                                       # fuels must not sink the build
        print(f"[epf] fuels skipped: {type(e).__name__}: {str(e)[:60]}")

    # --- calendar (known forever) ---
    idx = df.index
    df["hour"] = idx.hour
    df["dow"] = idx.dayofweek
    df["month"] = idx.month
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    df["is_holiday"] = pd.Series(idx.strftime("%Y-%m-%d"), index=idx).isin(IT_HOLIDAYS).astype(int)

    df.attrs["zone"] = zone
    df.attrs["target"] = "price"
    df.attrs["vintage_warning"] = ("forecasts are the CURRENT ENTSO-E version, not the vintage "
                                   "known at gate closure; metrics are an upper bound on skill")
    return df


def publish_dataset(zone: str = "IT_NORD", start=None, end=None) -> pd.DataFrame:
    """Write data/epf/dataset_<zone>.parquet for the epf-toolkit to consume."""
    df = build_dataset(zone, start, end)
    EPF_DIR.mkdir(parents=True, exist_ok=True)
    out = EPF_DIR / f"dataset_{zone}.parquet"
    df.to_parquet(out)
    feats = [c for c in df.columns if c != "price"]
    print(f"[ok] {out.name} — {len(df)} hourly rows, {len(feats)} features, "
          f"{df.index.min():%Y-%m-%d} -> {df.index.max():%Y-%m-%d}")
    print(f"     target: price | features: {', '.join(feats)}")
    miss = df[feats].isna().mean().sort_values(ascending=False)
    bad = miss[miss > 0.02]
    if len(bad):
        print(f"     [warn] features with >2% missing: {dict(bad.round(3))}")
    print("     [note] forecasts are the current ENTSO-E vintage, not point-in-time — "
          "treat backtest skill as an upper bound (see docstring).")
    return df


def snapshot_forecast_vintage(zone: str = "IT_NORD") -> Path | None:
    """Append today's day-ahead forecast, AS PUBLISHED NOW, to a point-in-time archive.

    This is the only way to earn an honest backtest later: ENTSO-E overwrites, so vintages must
    be captured as they happen. Run it daily (after ~14:00, once tomorrow is published) and in a
    few months the backtest can stand on data that was really knowable at the time.
    """
    now = pd.Timestamp.now(tz=cfg.TZ)
    fc = fetch_da_forecasts(zone, now.normalize(), now.normalize() + pd.Timedelta(days=2))
    if fc.empty:
        print("[epf] no forecast to snapshot yet")
        return None
    fc = fc.reset_index().rename(columns={fc.index.name or "index": "delivery_time"})
    fc["captured_at"] = now.isoformat()                 # the vintage stamp: when we saw it
    VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = VINTAGE_DIR / f"{zone}_{now:%Y%m%d_%H%M}.parquet"
    fc.to_parquet(out, index=False)
    print(f"[ok] vintage snapshot {out.name} — {len(fc)} hours captured at {now:%Y-%m-%d %H:%M}")
    return out


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--snapshot" in sys.argv:
        snapshot_forecast_vintage(args[0] if args else "IT_NORD")
    else:
        publish_dataset(args[0] if args else "IT_NORD")
