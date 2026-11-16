"""Gas price — EEX EGSI TTF Day, with an incremental local cache.

Why this series (see the fuels discussion in docs): the marginal CCGT's opportunity cost of
gas for power delivered on day D is the price of gas FOR DAY D — a day-ahead spot product, not
the front-month. EGSI Day is EEX's volume-weighted index over all day-ahead trades for the
delivery day, so it is more representative than a single closing settlement, and it carries a
value for every calendar day (weekends included, when the power plants also run).

Hub: TTF. Italy's PSV has no spot product on EEX; the market quotes PSV as TTF + spread
(~2-3 EUR/MWh, transport from the north). That basis is NOT applied here — it is a declared
gap (README, Known gaps).

Gas day: EEX delivers 06:00 D -> 06:00 D+1. We map the gas day D onto the electricity day D
(same value for every slot of D) and ignore the 6-hour offset — declared, not hidden.

Timing: EGSI for delivery D closes at the end of trading on D-1, i.e. AFTER the noon day-ahead
power auction for D. Fine for explaining a price (SRMC, spark spread); a forecaster must lag it
(epf_dataset already uses D-2).

Source and use: the endpoint is the one EEX's public Market Data Hub page reads from. It is
not a documented API and serves a rolling ~1-year window, so we accumulate history locally in
data/raw/gas_egsi.parquet (git-ignored). EEX's terms forbid systematic republication: this is
for LOCAL, personal use only — never publish the series or commit the cache.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://api.eex-group.com/pub/market-data/table-data"
PARAMS = {"shortCode": "EEX EGSI TTF Day", "commodity": "NATGAS", "pricing": "I",
          "area": "TTF", "product": "EGSI", "isRolling": "true"}
# The endpoint serves the public EEX page and expects that page's origin.
HEADERS = {"Accept": "application/json", "Origin": "https://www.eex.com",
           "Referer": "https://www.eex.com/", "User-Agent": "Mozilla/5.0"}

CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "gas_egsi.parquet"
RETRIES, BACKOFF_S = 3, 10
PLAUSIBLE = (5.0, 300.0)           # EUR/MWh_th — outside this, the parse is wrong, not the market


def parse(payload: dict) -> pd.Series:
    """EEX table-data JSON -> daily Series (EUR/MWh_th) indexed by DELIVERY day (naive date).

    Rows without a price are dropped; if a delivery day appears twice, the latest trade date
    wins. Header is read by name, so a column reorder on EEX's side does not shift the data.
    """
    header, data = payload.get("header") or [], payload.get("data") or []
    if not data:
        return pd.Series(dtype=float, name="gas_ttf")
    missing = {"deliveryDay", "settlPx", "tradeDate"} - set(header)
    if missing:
        raise ValueError(f"EEX payload missing columns {sorted(missing)}; header={header}")
    df = pd.DataFrame(data, columns=header).dropna(subset=["settlPx"])
    df["day"] = pd.to_datetime(df["deliveryDay"]).dt.normalize()
    df = df.sort_values(["day", "tradeDate"]).drop_duplicates("day", keep="last")
    return df.set_index("day")["settlPx"].astype(float).rename("gas_ttf").rename_axis(None)


def fetch(start, end) -> pd.Series:
    """One request to EEX for [start, end] (dates), with retry on transient errors."""
    params = {**PARAMS, "startDate": pd.Timestamp(start).date().isoformat(),
              "endDate": pd.Timestamp(end).date().isoformat()}
    delay = BACKOFF_S
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return parse(r.json())
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if attempt == RETRIES or (status is not None and status < 500):
                raise
            print(f"[gas] EEX {type(e).__name__} — retry {attempt}/{RETRIES - 1} in {delay}s")
            time.sleep(delay)
            delay *= 2


def merge(cached: pd.Series, new: pd.Series) -> tuple[pd.Series, list[str]]:
    """Union of cache and fresh download. A revised value wins and is reported, so a silent
    change in history never goes unnoticed; the cache never shrinks."""
    log = []
    common = cached.index.intersection(new.index)
    diff = (cached[common] - new[common]).abs() > 1e-6
    for d in common[diff.values]:
        log.append(f"{d.date()} revised {cached[d]:.3f} -> {new[d]:.3f}")
    out = pd.concat([cached, new])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.rename("gas_ttf"), log


def _check(s: pd.Series) -> None:
    lo, hi = PLAUSIBLE
    bad = s[(s < lo) | (s > hi)]
    if len(bad):
        raise ValueError(f"EGSI values outside {PLAUSIBLE} EUR/MWh, e.g. {bad.iloc[:3].to_dict()}")


def gas_series(start, end, cache_path: Path = CACHE) -> pd.Series:
    """Daily EGSI TTF for [start, end], served from the local cache after refreshing it.

    If EEX is unreachable or returns garbage, the cache is served as-is (stale but valid)
    rather than failing the build: the panel shows the last good day and its date.
    """
    cached = (pd.read_parquet(cache_path)["gas_ttf"] if cache_path.exists()
              else pd.Series(dtype=float, name="gas_ttf"))
    try:
        new = fetch(start, end)
        _check(new)
        if new.empty:
            print("[gas] EEX returned no rows — serving cache")
        else:
            merged, log = merge(cached, new)
            for line in log:
                print(f"[gas] {line}")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_frame().to_parquet(cache_path)
            print(f"[gas] EGSI TTF: +{len(merged) - len(cached)} days, {len(merged)} cached "
                  f"({merged.index.min().date()} -> {merged.index.max().date()})")
            cached = merged
    except Exception as e:
        if cached.empty:
            raise
        print(f"[gas] EEX refresh failed ({type(e).__name__}: {str(e)[:60]}) — serving cache "
              f"up to {cached.index.max().date()}")
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if s.tzinfo is not None:
        s, e = s.tz_localize(None), e.tz_localize(None)
    return cached[(cached.index >= s) & (cached.index <= e)]
