"""Fetch layer — ENTSO-E only for this first slice.

One responsibility: pull raw series for a zone/window and hand back tidy pandas
objects. No transforms here. Requires env var ENTSOE_TOKEN.
"""
from __future__ import annotations

import os
import time
import pandas as pd
import requests
from entsoe import EntsoePandasClient

RETRIES = 4            # attempts per query on a transient server error
BACKOFF_S = 15         # first wait; doubles each attempt (15, 30, 60)


def _client() -> EntsoePandasClient:
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise RuntimeError("Set ENTSOE_TOKEN in the environment (free ENTSO-E token).")
    return EntsoePandasClient(api_key=token)


def _transient(e: Exception) -> bool:
    """5xx (incl. ENTSO-E's non-standard 599 'overloaded') and timeouts are worth retrying.
    entsoe-py's own retry only covers connection errors, so a 599 would otherwise sink the
    whole zone. 4xx and NoMatchingDataError are real answers — never retried."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return e.response.status_code >= 500
    return isinstance(e, (requests.Timeout, requests.ConnectionError))


def _call(label: str, fn, *args, **kwargs):
    delay = BACKOFF_S
    for attempt in range(1, RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == RETRIES or not _transient(e):
                raise
            print(f"[fetch] {label}: {type(e).__name__} ({str(e)[:40]}) — "
                  f"retry {attempt}/{RETRIES - 1} in {delay}s")
            time.sleep(delay)
            delay *= 2


def fetch_zone(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Return raw series for one bidding zone: price, load, generation, net_import.

    net_import sums ALL borders of the zone (inter-zonal + international), which is
    exactly the zone's net import for the energy balance (see node A).
    """
    c = _client()

    w = dict(start=start, end=end)

    price = _call(f"{zone} price", c.query_day_ahead_prices, zone, **w)
    price = price.iloc[:, 0] if isinstance(price, pd.DataFrame) else price
    price.name = "price_zonal"

    load = _call(f"{zone} load", c.query_load, zone, **w)
    load = load.iloc[:, 0] if isinstance(load, pd.DataFrame) else load
    load.name = "load"

    gen = _call(f"{zone} gen", c.query_generation, zone, **w)

    imp = _call(f"{zone} import", c.query_physical_crossborder_allborders, zone, **w, export=False)
    exp = _call(f"{zone} export", c.query_physical_crossborder_allborders, zone, **w, export=True)
    imp = imp.sum(axis=1) if isinstance(imp, pd.DataFrame) else imp
    exp = exp.sum(axis=1) if isinstance(exp, pd.DataFrame) else exp
    net_import = (imp - exp).rename("net_import")

    return {"price": price, "load": load, "gen": gen, "net_import": net_import}
