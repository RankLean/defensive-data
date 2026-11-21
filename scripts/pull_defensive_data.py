"""
pull_defensive_data.py
Pulls: prices + fundamentals (yfinance), Ken French factors,
FRED macro series, analyst estimates (yfinance), annual market
outlook summaries (public PDFs where available).
Outputs land in data/.
Run: python scripts/pull_defensive_data.py
"""

import os, sys, warnings
from pathlib import Path
from datetime import datetime, date

warnings.filterwarnings("ignore")
Path("data").mkdir(exist_ok=True)
LOG = []

try:
    import pandas as pd
except ImportError as e:
    Path("data/_pull_log.csv").write_text(f"source,status,note,ts\npull_defensive_data,fail,import error: {e},{datetime.utcnow().isoformat()}\n")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError as e:
    pd.DataFrame([{"source": "pull_defensive_data", "status": "fail",
                   "note": f"yfinance not installed: {e}",
                   "ts": datetime.utcnow().isoformat()}]).to_csv("data/_pull_log.csv", mode="a", index=False, header=False)
    sys.exit(1)

import requests

def log(src, status, note=""):
    LOG.append({"source": src, "status": status, "note": note, "ts": datetime.utcnow().isoformat()})
    print(f"[{status}] {src}" + (f" — {note}" if note else ""))

def save(df, name):
    df.to_csv(f"data/{name}", index=False)
    log(name, "ok", f"{len(df)} rows")

def tickers():
    t = [l.strip() for l in Path("tickers.txt").read_text().splitlines()
         if l.strip() and not l.startswith("#")]
    return t

# ── 1. Prices 1980–today ────────────────────────────────────────────────────
def pull_prices():
    syms = tickers() + ["SPY", "QQQ", "^GSPC", "^IXIC", "^DJI", "^VIX",
                         "TLT", "IEF", "GLD", "XLV", "XLP", "XLU", "XLE",
                         "XLF", "XLK", "XLI", "XLB", "XLRE", "XLC", "XLY"]
    syms = sorted(set(syms))
    try:
        raw = yf.download(syms, start="1980-01-01", auto_adjust=True,
                          progress=False, threads=True)
        close = raw["Close"].reset_index()
        close.columns.name = None
        close = close.rename(columns={"Date": "date"})
        close["date"] = pd.to_datetime(close["date"]).dt.date.astype(str)
        save(close, "prices_daily.csv")
    except Exception as e:
        log("prices_daily", "fail", str(e))

# ── 2. Fundamentals + analyst estimates ─────────────────────────────────────
def pull_fundamentals():
    rows = []
    est_rows = []
    for sym in tickers():
        try:
            tk = yf.Ticker(sym)
            info = tk.info or {}
            rows.append({
                "ticker": sym,
                "as_of": date.today().isoformat(),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "pe_trailing": info.get("trailingPE"),
                "pe_forward": info.get("forwardPE"),
                "pb": info.get("priceToBook"),
                "ps": info.get("priceToSalesTrailing12Months"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "gross_margin": info.get("grossMargins"),
                "op_margin": info.get("operatingMargins"),
                "net_margin":
