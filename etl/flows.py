"""Cross-border flows per interconnector — ENTSO-E physical flows (free).

Our main series carries `net_import` aggregated over ALL borders, which is what the energy
balance needs. This splits the northern border into its four interconnectors, which is what a
trader wants: *where* the import is coming from. French nuclear, Swiss hydro, Austrian or
Slovenian flows are different stories, and a border sitting at its limit is a constraint that
shows up in the zonal price.

Provenance: these are ENTSO-E **physical** flows (Observed). Terna's public dashboard shows
*scheduled commercial exchange* — a related but different quantity, so the numbers won't tie
out exactly. We publish what we measure and say which it is.

Scope: IT_NORD's international borders only (FR, CH, AT, SI) — the bulk of Italian imports.
Greece/Montenegro (south) and Malta (Sicily) sit on other zones and are not covered.
"""
from __future__ import annotations

import os
import pandas as pd

# IT_NORD's international neighbours (entsoe-py NEIGHBOURS also lists the legacy DE_AT_LU
# zone, abolished in 2018, and the internal IT_CNOR link — both deliberately excluded).
BORDERS = {
    "FR": "France",
    "CH": "Switzerland",
    "AT": "Austria",
    "SI": "Slovenia",
}


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    from entsoe import EntsoePandasClient
    return EntsoePandasClient(api_key=os.environ["ENTSOE_TOKEN"])


def fetch_border_flows(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Net physical flow per border (MW, positive = into `zone`).

    One column per neighbour. A border that fails or has no data is skipped with a warning
    rather than sinking the others.
    """
    c = _client()
    out = {}
    for code in BORDERS:
        try:
            imp = c.query_crossborder_flows(code, zone, start=start, end=end)   # neighbour -> zone
            exp = c.query_crossborder_flows(zone, code, start=start, end=end)   # zone -> neighbour
            net = imp.subtract(exp, fill_value=0.0)
            out[code] = net
        except Exception as e:
            print(f"[flows] {code}: skipped ({type(e).__name__}: {str(e)[:50]})")
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, axis=1)
    df.columns = list(out.keys())
    return df.resample("h").mean()          # hourly, matching the rest of the dashboard's reads
