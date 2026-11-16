"""Fuel & carbon anchors — TTF gas (EEX EGSI, see gas_eex.py) and EUA carbon (yfinance).

These are slow EOD anchors (daily), a different timescale from the 15-min electricity data.
From them we build the marginal combined-cycle gas turbine's short-run marginal cost (SRMC)
and, joined with the power price, the clean spark spread — the *cost* side of "why this
price": when the regime panel says "cost-driven", this shows which cost moved.

Provenance:
- gas is Observed: EEX EGSI TTF Day, the volume-weighted day-ahead index for the delivery day
  (Yahoo's TTF=F front-month stopped serving history in Nov 2026, and a front-month is the
  wrong product for a marginal cost anyway). Local use only — see gas_eex.py.
- carbon (EUA) is Observed EOD (Yahoo CO2.L) — a proxy for the exact ICE settlement.
- efficiency (eta) and the gas emission factor are ASSUMPTIONS — chosen parameters of the
  marginal CCGT, not measured data.

SRMC per MWh_e = (gas[EUR/MWh_th] + EUA[EUR/t] * EF_GAS[tCO2/MWh_th]) / eta
  where dividing by eta converts thermal input to electrical output (you burn 1/eta MWh of
  gas per MWh_e), so per-MWh_e emissions work out to EF_GAS/eta (~0.40 tCO2/MWh_e at 0.50).
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

# --- marginal-CCGT assumptions (declared, not measured) ---
ETA = 0.50                 # thermal efficiency of a modern combined-cycle gas turbine
EF_GAS = 0.20              # tCO2 per MWh_thermal of natural gas (physical, ~0.18-0.20)

# --- sources ---
CO2_TICKER = "CO2.L"       # EUA-linked instrument on LSE
CO2_SCALE = 1.0            # multiply raw close -> EUR/tCO2 (adjust if CO2.L units differ)


def _close(ticker: str, start, end) -> pd.Series:
    """Daily close for a ticker, robust to yfinance's MultiIndex columns."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):          # MultiIndex (field, ticker) -> single series
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    return close.astype(float)


def fetch_fuels(start, end) -> pd.DataFrame:
    """Daily gas (EUR/MWh_th), EUA (EUR/tCO2) and SRMC (EUR/MWh_e)."""
    from .gas_eex import gas_series
    gas = gas_series(start, end)                  # every calendar day, by delivery day
    eua = (_close(CO2_TICKER, start, end) * CO2_SCALE).rename("eua")
    # EUA does not trade at weekends: carry the last close; gas has its own weekend values
    df = pd.concat([gas, eua], axis=1).sort_index()
    df["eua"] = df["eua"].ffill()
    df["srmc"] = (df["gas_ttf"] + df["eua"] * EF_GAS) / ETA
    return df


def sanity(df: pd.DataFrame) -> list[str]:
    """Catch unit/currency problems early (esp. CO2.L, whose quoting we must verify)."""
    msgs = []
    g, c = df["gas_ttf"].dropna(), df["eua"].dropna()
    if not g.empty and not (10 <= g.iloc[-1] <= 200):
        msgs.append(f"gas {g.iloc[-1]:.1f} outside plausible TTF range 10-200 EUR/MWh")
    if not c.empty and not (30 <= c.iloc[-1] <= 150):
        msgs.append(f"EUA {c.iloc[-1]:.1f} outside plausible 30-150 EUR/t — "
                    f"check CO2.L units and set CO2_SCALE")
    return msgs
