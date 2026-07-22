import yfinance as yf
for tkr in ["TTF=F", "KRBN", "CO2.L"]:      # TTF gas, carbon ETF proxy, (a EUA proxy)
    df = yf.download(tkr, start="2025-10-01", end="2026-07-10", progress=False)
    print(tkr, "->", 0 if df.empty else len(df), "righe",
          "| ultimo:", None if df.empty else df.index[-1].date())