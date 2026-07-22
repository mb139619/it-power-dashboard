import os, pandas as pd
from dotenv import load_dotenv; load_dotenv()
import terna as trn

c = trn.TernaPandasClient(api_key=os.environ["TERNA_API_KEY"],
                          api_secret=os.environ["TERNA_API_SECRET"])
start = pd.Timestamp("2026-07-14", tz="Europe/Rome")
end   = pd.Timestamp("2026-07-15", tz="Europe/Rome")

g = c.get_actual_generation(start=start, end=end,
        gen_type=['Self-consumption','Photovoltaic'])
g.index = pd.to_datetime(g.index)

for src in ["Self-consumption", "Photovoltaic"]:
    s = g[g["primary_source"] == src]["actual_generation_GWh"] * 1000   # -> MW
    h = s.groupby(s.index.hour).mean()
    print(f"\n=== {src} (MW, nazionale) ===")
    print("  notte 00-03 :", round(h.loc[0:3].mean()))
    print("  mezzogiorno :", round(h.loc[11:14].mean()))
    print("  picco       :", round(h.max()), "alle", h.idxmax())
    print("  profilo:", [round(h.get(x, 0)) for x in range(0, 24, 3)])