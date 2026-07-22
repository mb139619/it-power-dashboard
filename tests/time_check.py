import time, os, pandas as pd
from dotenv import load_dotenv; load_dotenv()
from entsoe import EntsoePandasClient
c = EntsoePandasClient(api_key=os.environ["ENTSOE_TOKEN"])
start = pd.Timestamp("2026-06-25", tz="Europe/Rome")
end   = pd.Timestamp("2026-07-02", tz="Europe/Rome")

def timeit(label, fn):
    t = time.time()
    try:
        fn(); print(f"{label:12s} {time.time()-t:6.1f}s  OK")
    except Exception as e:
        print(f"{label:12s} {time.time()-t:6.1f}s  ERR {type(e).__name__}")

for zone in ["IT_NORD", "IT_CNOR"]:
    print(f"--- {zone} ---")
    timeit("prices",     lambda z=zone: c.query_day_ahead_prices(z, start=start, end=end))
    timeit("load",       lambda z=zone: c.query_load(z, start=start, end=end))
    timeit("generation", lambda z=zone: c.query_generation(z, start=start, end=end))
    timeit("import",     lambda z=zone: c.query_physical_crossborder_allborders(z, start=start, end=end, export=False))
    timeit("export",     lambda z=zone: c.query_physical_crossborder_allborders(z, start=start, end=end, export=True))