"""Day-ahead outlook — tomorrow's expected residual demand (ENTSO-E forecasts, free).

Everything else in this project explains why the price is where it *is*. This is the one
forward-looking piece: ENTSO-E publishes day-ahead forecasts of load, wind and solar, so we
can compute tomorrow's **net load** (load - wind - solar, the forward twin of our residual)
and compare it to today. A higher net-load day means more must come from dispatchable plant,
climbing the merit order -> upward pressure on price. That day-over-day delta is a directional,
tradeable read.

Provenance: these are **forecasts** — model outputs, not observations. Badged as such.
Net load here is load - (wind + solar) forecast; run-of-river/geo are ~flat must-run and
cancel in the day-over-day delta, so they're omitted for the forward view.
"""
from __future__ import annotations

import os
import pandas as pd


def _client():
    from dotenv import load_dotenv
    load_dotenv()
    from entsoe import EntsoePandasClient
    return EntsoePandasClient(api_key=os.environ["ENTSOE_TOKEN"])


def fetch_net_load_forecast(zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Hourly day-ahead net-load forecast (MW) = load_fc - solar_fc - wind_fc."""
    c = _client()
    load = c.query_load_forecast(zone, start=start, end=end)
    load_s = load.iloc[:, 0] if hasattr(load, "columns") else load
    ws = c.query_wind_and_solar_forecast(zone, start=start, end=end)
    solar = ws["Solar"] if "Solar" in ws.columns else pd.Series(0.0, index=ws.index)
    wind_cols = [x for x in ws.columns if "Wind" in x]
    wind = ws[wind_cols].sum(axis=1) if wind_cols else pd.Series(0.0, index=ws.index)
    df = pd.concat([load_s.rename("load"), solar.rename("solar"), wind.rename("wind")], axis=1)
    df = df.resample("h").mean()                      # normalise to hourly
    return (df["load"] - df["solar"] - df["wind"]).rename("net_load").dropna()
