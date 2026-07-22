import pandas as pd
from dotenv import load_dotenv; load_dotenv()
from etl.fetch import fetch_zone
from etl.transform import split_generation, closure_error

start = pd.Timestamp("2026-06-10", tz="Europe/Rome")
end   = pd.Timestamp("2026-06-17", tz="Europe/Rome")
raw = fetch_zone("IT_NORD", start, end)
agg, pump = split_generation(raw["gen"])
idx = raw["load"].index
agg  = agg.reindex(idx); pump = pump.reindex(idx).fillna(0.0)
ni   = raw["net_import"].reindex(idx); load = raw["load"].reindex(idx)
eps  = closure_error(load, agg, pump, ni).reindex(idx)

def swing(s):  # ampiezza dell'oscillazione DENTRO l'ora (std del valore meno la media oraria)
    s = pd.Series(s).astype(float).dropna()
    hm = s.groupby(s.index.floor("h")).transform("mean")
    return (s - hm).std()

comps = {"eps": eps, "load": load, "gen_total": agg.sum(axis=1),
         "net_import": ni, "pump": pump, "solar": agg.get("Solar")}
for k, v in comps.items():
    if v is not None:
        print(f"{k:12s} swing intra-oraria = {swing(v):8.1f} MW")

print(f"\neps 15-min swing = {swing(eps):.0f} MW  ->  eps orario e' liscio per costruzione")