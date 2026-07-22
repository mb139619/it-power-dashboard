"""Measure ENTSO-E's real settle lag — don't guess it.

The dashboard refuses to read actuals inside the publication window (SPA constant SETTLE_MIN,
default 60 min). That constant is an ASSUMPTION. This measures it from your own data instead:
run it, re-run the ETL later, run it again, and it reports which slots got revised and by how
much. Set SETTLE_MIN to comfortably cover the revision horizon you actually observe.

    python tools/settle_check.py            # snapshot the current tail
    python -m etl.build IT_NORD             # ... later, refresh the data
    python tools/settle_check.py            # compare: what changed, and how far back?

Revisions are expected: Reg. 543/2013 sets publication deadlines per data item and providers
overwrite earlier submissions as units report in. The question is only *how far back* they
reach for your zone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SNAP = Path(__file__).resolve().parent / "_settle_snapshot.json"
COLS = ["load", "solar_gross", "wind", "gen_thermal"]
TAIL = 24                                    # how many trailing slots to watch


def _tail(zone: str) -> dict:
    s = json.loads((ROOT / "data" / f"series_{zone}.json").read_text())
    idx = pd.to_datetime(s["index"], utc=True).tz_convert("Europe/Rome")
    out = {"zone": zone, "generated_at": None, "rows": {}}
    meta_p = ROOT / "data" / f"meta_{zone}.json"
    if meta_p.exists():
        out["generated_at"] = json.loads(meta_p.read_text()).get("generated_at")
    for i in range(max(0, len(idx) - TAIL), len(idx)):
        out["rows"][idx[i].isoformat()] = {
            c: s["columns"][c]["values"][i] for c in COLS if c in s["columns"]
        }
    return out


def main(zone: str = "IT_NORD") -> None:
    now = _tail(zone)
    if not SNAP.exists():
        SNAP.write_text(json.dumps(now, indent=1))
        print(f"snapshot saved ({zone}, last {TAIL} slots, run {now['generated_at']}).")
        print("re-run the ETL later, then run this again to see what got revised.")
        return

    old = json.loads(SNAP.read_text())
    if old.get("zone") != zone:
        print(f"snapshot is for {old.get('zone')}, not {zone} — delete {SNAP.name} first")
        return
    print(f"comparing {zone}:  old run {old['generated_at']}  ->  new run {now['generated_at']}\n")

    revised, newest_revision = 0, None
    for ts, oldrow in old["rows"].items():
        newrow = now["rows"].get(ts)
        if newrow is None:
            continue
        for c, ov in oldrow.items():
            nv = newrow.get(c)
            if ov is None and nv is None:
                continue
            if ov is None or nv is None or abs((nv or 0) - (ov or 0)) > 1.0:
                pct = "" if not ov else f" ({(nv - ov) / ov * 100:+.0f}%)"
                print(f"  {ts[:16]}  {c:12} {ov} -> {nv}{pct}")
                revised += 1
                newest_revision = ts if newest_revision is None else max(newest_revision, ts)

    if not revised:
        print("  no revisions in the overlapping tail — the window you kept was already settled.")
    else:
        oldest = min(t for t in old["rows"] if any(
            (old["rows"][t].get(c) is None) != (now["rows"].get(t, {}).get(c) is None)
            or (old["rows"][t].get(c) is not None and now["rows"].get(t, {}).get(c) is not None
                and abs(now["rows"][t][c] - old["rows"][t][c]) > 1.0)
            for c in COLS if c in old["rows"][t]))
        span = (pd.Timestamp(now["generated_at"]) - pd.Timestamp(oldest)).total_seconds() / 60
        print(f"\n  {revised} values revised; oldest revised slot {oldest[:16]}")
        print(f"  -> revisions reach back ~{span:.0f} min before the new run.")
        print(f"  Set SETTLE_MIN >= that (currently 60) to stay outside the revision horizon.")

    SNAP.write_text(json.dumps(now, indent=1))
    print(f"\nsnapshot updated to the current run.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "IT_NORD")
