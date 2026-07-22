"""Fetch layer — ENTSO-E only for this first slice.

One responsibility: pull raw series for a zone/window and hand back tidy pandas
objects. No transforms here. Requires env var ENTSOE_TOKEN.
"""
from __future__ import annotations

import os
import pandas as pd
from entsoe import EntsoePandasClient


def _client() -> EntsoePandasClient:
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        raise RuntimeError("Set ENTSOE_TOKEN in the environment (free ENTSO-E token).")
    return EntsoePandasClient(api_key=token)


def fetch_zone(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Return raw series for one bidding zone: price, load, generation, net_import.

    net_import sums ALL borders of the zone (inter-zonal + international), which is
    exactly the zone's net import for the energy balance (see node A).
    """
    c = _client()

    price = c.query_day_ahead_prices(zone, start=start, end=end)
    price = price.iloc[:, 0] if isinstance(price, pd.DataFrame) else price
    price.name = "price_zonal"

    load = c.query_load(zone, start=start, end=end)
    load = load.iloc[:, 0] if isinstance(load, pd.DataFrame) else load
    load.name = "load"

    gen = c.query_generation(zone, start=start, end=end)

    imp = c.query_physical_crossborder_allborders(zone, start=start, end=end, export=False)
    exp = c.query_physical_crossborder_allborders(zone, start=start, end=end, export=True)
    imp = imp.sum(axis=1) if isinstance(imp, pd.DataFrame) else imp
    exp = exp.sum(axis=1) if isinstance(exp, pd.DataFrame) else exp
    net_import = (imp - exp).rename("net_import")

    return {"price": price, "load": load, "gen": gen, "net_import": net_import}
