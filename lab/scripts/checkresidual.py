import json, pandas as pd
s = json.load(open("data/series_IT_NORD.json"))
idx = pd.to_datetime(s["index"], utc=True).tz_convert("Europe/Rome")
c = lambda k: pd.Series(s["columns"][k]["values"], index=idx)

gen = c("gen_thermal") + c("solar_gross") + c("wind") + c("gen_hydro") + c("geothermal") + c("gen_other")
df = pd.DataFrame({"load": c("load"), "gen": gen, "pump": c("pumping"),
                   "imp": c("net_import"), "solar": c("solar_gross")}).dropna()
df["eps"] = df["load"] - (df["gen"] - df["pump"] + df["imp"])

for day in ["2026-07-14", "2025-10-15"]:          # un giorno d'estate e uno d'autunno
    d = df[df.index.date == pd.Timestamp(day).date()].resample("h").mean()
    if d.empty: continue
    print(f"\n=== {day} ===")
    print(d[["load","gen","imp","solar","eps"]].round(0).to_string())
    night = d[d.index.hour < 4]["eps"].mean()
    noon  = d[(d.index.hour >= 11) & (d.index.hour <= 14)]["eps"].mean()
    print(f"  eps notte(0-3) {night:.0f} | eps mezzogiorno(11-14) {noon:.0f} | campana = {night-noon:.0f} MW")