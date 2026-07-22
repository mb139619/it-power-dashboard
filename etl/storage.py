"""Gas storage — AGSI+ (GIE) via gie-py (free, register for a key like ENTSO-E).

Storage is *the* gas fundamental: level vs the seasonal norm tells you whether gas is likely
bid or offered. Low storage for the time of year -> gas bid -> TTF up -> SRMC up -> the clean
spark spread compresses. This closes the gas chain that the fundamentals panel opened.

Provenance is handed to us by the source: GIE stamps each day's `status` as
C (confirmed) / E (estimated) / N (no data) — we map that straight to our badges.

Key field: `full` = % of working gas volume in store. The seasonal band is the historical
min/max/mean of `full` per day-of-year; the current year is read against it.
"""
from __future__ import annotations

import os
import pandas as pd

STATUS_MAP = {"C": "observed", "E": "estimated", "N": "proxy"}  # GIE data-quality flag -> badge


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("AGSI_KEY")
    if not key:
        raise RuntimeError("AGSI_KEY not set — register at https://agsi.gie.eu/account")
    from gie import GiePandasClient
    return GiePandasClient(api_key=key)


def fetch_storage(country: str = "IT", start="2019-01-01", end=None) -> pd.DataFrame:
    """Daily storage for a country: full %, gas in store (TWh), trend, net flow, GIE status."""
    end = end or pd.Timestamp.now().strftime("%Y-%m-%d")
    df = _client().query_gas_country(country, start=start, end=end).sort_index()
    df.index = pd.to_datetime(df.index)
    keep = ["full", "gasInStorage", "trend", "netWithdrawal", "status"]
    out = df[[c for c in keep if c in df.columns]].copy()
    for c in ("full", "gasInStorage", "trend", "netWithdrawal"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def seasonal_band(full: pd.Series, hist_years, current_year: int, prev_year=None):
    """Historical min/max/mean of `full` per day-of-year, plus the current and previous year."""
    d = full.dropna().to_frame("full")
    d["year"] = d.index.year
    d["doy"] = d.index.dayofyear
    band = d[d["year"].isin(hist_years)].groupby("doy")["full"].agg(["min", "max", "mean"])
    cur = d[d["year"] == current_year].set_index("doy")["full"]
    prev = d[d["year"] == prev_year].set_index("doy")["full"] if prev_year is not None else None
    return band, cur, prev
