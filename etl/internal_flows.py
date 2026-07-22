"""Physical flows BETWEEN the Italian bidding zones — Terna transparency API.

The map already shows where prices diverge. This shows why: in a coupled market two adjacent
zones clear at the same price unless the link between them is constrained, so the flows are the
mechanism behind every zonal spread. ENTSO-E gives us the foreign borders; the internal links
are Terna's.

Credentials: register at developer.terna.it (client id + secret, both free) and put them in
.env as TERNA_API_KEY / TERNA_API_SECRET. Without them this module simply does nothing and the
map renders exactly as before — no third registration required to run the project.

Provenance: Observed (Terna physical flows). Note this is a DIFFERENT source from the rest of
the power data (ENTSO-E), so the two are not guaranteed to reconcile to the last MW.
"""
from __future__ import annotations

import os
import re

import pandas as pd

# Terna's English zone labels -> our codes. The API spells them out in the `flow` column,
# e.g. "Centre-South -> Centre-North".
TERNA_ZONE = {
    "North": "NORD",
    "Centre-North": "CNOR",
    "Centre-South": "CSUD",
    "South": "SUD",
    "Calabria": "CALA",
    "Sicily": "SICI",
    "Sardinia": "SARD",
}

# The seven physical links of the Italian grid, as (from, to) in our codes. A flow's sign is
# relative to the direction in its own name: "Sicily -> Calabria = -313" means 313 MW actually
# moved Calabria -> Sicily.
LINKS = [("NORD", "CNOR"), ("CNOR", "CSUD"), ("CSUD", "SUD"),
         ("SUD", "CALA"), ("CALA", "SICI"), ("SARD", "CNOR"), ("SARD", "CSUD")]


def available() -> bool:
    """True when Terna credentials are present — the caller degrades gracefully if not."""
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.environ.get("TERNA_API_KEY") and os.environ.get("TERNA_API_SECRET"))


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    import terna
    return terna.TernaPandasClient(api_key=os.environ["TERNA_API_KEY"],
                                   api_secret=os.environ["TERNA_API_SECRET"])


def _parse_link(label: str) -> tuple[str, str] | None:
    """'Centre-South -> Centre-North' -> ('CSUD', 'CNOR'); unknown labels are skipped."""
    parts = re.split(r"\s*->\s*", str(label))
    if len(parts) != 2:
        return None
    a, b = (TERNA_ZONE.get(p.strip()) for p in parts)
    return (a, b) if a and b else None


def fetch_internal_flows(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Wide frame of net flows in MW: one column per link, named '<FROM>-<TO>'.

    Positive means power moved FROM -> TO, using the canonical direction in LINKS (not Terna's
    label order), so signs are consistent across links.
    """
    df = _client().get_physical_internal_flow(start=start, end=end)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    col = "physical_internal_flow_MW"
    out = {}
    for label, grp in df.groupby("flow"):
        link = _parse_link(label)
        if not link:
            continue
        a, b = link
        s = grp[col].astype(float)
        if (a, b) in LINKS:
            out[f"{a}-{b}"] = s
        elif (b, a) in LINKS:
            out[f"{b}-{a}"] = -s          # flip to the canonical direction
    return pd.DataFrame(out).sort_index() if out else pd.DataFrame()


def hourly_profiles(flows: pd.DataFrame, day) -> dict[str, list]:
    """24 hourly means per link for one calendar day — feeds the map's hour slider."""
    if flows.empty:
        return {}
    sub = flows[flows.index.date == day]
    if sub.empty:
        return {}
    hourly = sub.groupby(sub.index.hour).mean()
    return {c: [round(float(hourly[c].get(h)), 1) if h in hourly.index and pd.notna(hourly[c].get(h))
                else None for h in range(24)]
            for c in flows.columns}
