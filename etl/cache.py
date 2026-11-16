"""Incremental raw cache — download only what's missing.

The network is the bottleneck (cross-border import/export dominate: ~65% of a zone's
fetch time, because entsoe-py issues one request per border, twice). So we cache the RAW
ENTSO-E series per zone in data/raw/<zone>.parquet and, on later runs, fetch only the tail
we don't have — plus a 2-day overlap to absorb ENTSO-E's revisions of recent data.

Correctness note: only the DOWNLOAD is incremental. The transform always runs on the full
cached history in assemble(), so a revision that lands in the overlap propagates to every
derived column and the published series never depends on which runs happened before.

The generation frame has MultiIndex columns (type × Actual Aggregated/Consumption); we
flatten them for parquet and rebuild them on load, transparently to split_generation().
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from .fetch import fetch_zone

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
SEP = "\u2016"            # ‖ — a separator that never appears in ENTSO-E type names
GEN = "GEN" + SEP
OVERLAP_DAYS = 2


def _combine(raw: dict) -> pd.DataFrame:
    """Scalar series + flattened generation into one frame on a common time index."""
    df = pd.DataFrame({"price": raw["price"], "load": raw["load"],
                       "net_import": raw["net_import"]})
    gen = raw["gen"]
    if isinstance(gen.columns, pd.MultiIndex):
        gcols = {f"{GEN}{a}{SEP}{b}": gen[(a, b)] for (a, b) in gen.columns}
    else:
        gcols = {f"{GEN}{a}{SEP}Actual Aggregated": gen[a] for a in gen.columns}
    return df.join(pd.DataFrame(gcols), how="outer").sort_index()


def _split(df: pd.DataFrame, start=None, end=None) -> dict:
    """Inverse of _combine: back to the dict fetch_zone returns (gen with MultiIndex cols)."""
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index <= end]
    gcols = [c for c in df.columns if c.startswith(GEN)]
    gen = df[gcols].copy()
    gen.columns = pd.MultiIndex.from_tuples([tuple(c[len(GEN):].split(SEP)) for c in gcols])
    price = df["price"].rename("price_zonal")
    return {"price": price, "load": df["load"].rename("load"),
            "gen": gen, "net_import": df["net_import"].rename("net_import")}


def _save(df: pd.DataFrame, path: Path) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def fetch_zone_cached(zone: str, start: pd.Timestamp, end: pd.Timestamp,
                      overlap_days: int = OVERLAP_DAYS, rebuild: bool = False) -> dict:
    path = RAW_DIR / f"{zone}.parquet"

    if rebuild or not path.exists():
        df = _combine(fetch_zone(zone, start, end))
        _save(df, path)
        print(f"[cache] {zone}: full download, {len(df)} rows")
        return _split(df, start, end)

    cached = pd.read_parquet(path)
    # Note: we only ever grow the cache forward. Backward extension isn't a use case —
    # WINDOW_START is fixed after the 2025-10-01 15-min regime change, and requesting data
    # before it would mix hourly + 15-min frequencies, which the single_frequency guard in
    # build.publish() already rejects. So there's nothing to backfill here.
    last = cached.index.max()
    dl_start = max(start, last - pd.Timedelta(days=overlap_days))
    if dl_start >= end:
        print(f"[cache] {zone}: up to date ({len(cached)} rows)")
        return _split(cached, start, end)

    new = _combine(fetch_zone(zone, dl_start, end))
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()  # revisions win
    _save(combined, path)
    print(f"[cache] {zone}: +{len(combined)-len(cached)} rows (from {dl_start.date()}), "
          f"{len(combined)} total")
    return _split(combined, start, end)
