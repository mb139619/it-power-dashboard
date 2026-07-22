# 1) genera il forecast ADESSO (sono le 18:32, domani c'è di sicuro)
import subprocess, sys
subprocess.run([sys.executable, "-m", "etl.build", "--forecast"])

# 2) leggi cosa ha scritto
import json
d = json.load(open("data/forecast.json"))
print("giorni:", [x["date"] for x in d["days"]])
print("delta_mean:", d.get("delta_mean"), "| delta_peak:", d.get("delta_peak"))
print("generated_at:", d["generated_at"])