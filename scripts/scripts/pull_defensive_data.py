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

import pandas as pd
import yfinance as yf
import requests

warnings.filterwarnings("ignore")
Path("data").mkdir(exist_ok=True)
LOG = []

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
                "net_margin": info.get("profitMargins"),
                "debt_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "beta": info.get("beta"),
                "div_yield": info.get("dividendYield"),
                "payout_ratio": info.get("payoutRatio"),
                "revenue_ttm": info.get("totalRevenue"),
                "ebitda_ttm": info.get("ebitda"),
                "eps_ttm": info.get("trailingEps"),
                "eps_fwd": info.get("forwardEps"),
                "analyst_target": info.get("targetMeanPrice"),
                "analyst_low": info.get("targetLowPrice"),
                "analyst_high": info.get("targetHighPrice"),
                "analyst_count": info.get("numberOfAnalystOpinions"),
                "recommendation": info.get("recommendationKey"),
            })
            # earnings estimates
            try:
                ee = tk.earnings_estimate
                if ee is not None and not ee.empty:
                    ee = ee.reset_index().rename(columns={"index": "period"})
                    ee.insert(0, "ticker", sym)
                    est_rows.append(ee)
            except Exception:
                pass
        except Exception as e:
            log(f"fundamentals/{sym}", "fail", str(e))
    if rows:
        save(pd.DataFrame(rows), "fundamentals_snapshot.csv")
    if est_rows:
        save(pd.concat(est_rows, ignore_index=True), "earnings_estimates.csv")

# ── 3. Historical annual EPS + revenue (yfinance financials) ─────────────────
def pull_financials():
    rows = []
    for sym in tickers():
        try:
            tk = yf.Ticker(sym)
            inc = tk.income_stmt
            if inc is not None and not inc.empty:
                for col in inc.columns:
                    r = {"ticker": sym, "period": str(col)[:10]}
                    for idx in inc.index:
                        r[str(idx)] = inc.at[idx, col]
                    rows.append(r)
        except Exception as e:
            log(f"financials/{sym}", "fail", str(e))
    if rows:
        df = pd.DataFrame(rows)
        df.columns = [str(c).replace("\n", " ")[:60] for c in df.columns]
        save(df, "financials_annual.csv")

# ── 4. FRED macro series 1980–today ─────────────────────────────────────────
FRED_SERIES = {
    # sentiment / consumer
    "UMCSENT":   "UMich consumer sentiment",
    "CONCCONF":  "Conference Board consumer confidence",
    # activity
    "INDPRO":    "Industrial production index",
    "PAYEMS":    "Nonfarm payrolls",
    "UNRATE":    "Unemployment rate",
    "GDPC1":     "Real GDP (quarterly)",
    "HOUST":     "Housing starts",
    # inflation
    "CPIAUCSL":  "CPI all items",
    "CPILFESL":  "CPI core (ex food energy)",
    "PCEPI":     "PCE price index",
    "PCEPILFE":  "Core PCE",
    # rates
    "DFF":       "Fed funds rate (effective daily)",
    "DGS2":      "2-year Treasury yield",
    "DGS10":     "10-year Treasury yield",
    "DGS30":     "30-year Treasury yield",
    "T10Y2Y":    "10y-2y yield spread",
    "T10YFFM":   "10y-FFR spread",
    "BAMLH0A0HYM2": "HY OAS spread",
    "BAA10Y":    "BAA-10y credit spread",
    # financial stress
    "NFCI":      "Chicago Fed NFCI",
    "STLFSI4":   "St Louis Fed FSI",
    "VIXCLS":    "VIX (daily close)",
    # money / credit
    "M2SL":      "M2 money supply",
    "TOTALSL":   "Total consumer credit",
    # business cycle
    "USREC":     "NBER recession indicator",
    "USEPUINDXD":"Economic policy uncertainty",
    # sector relevant
    "DSPIC96":   "Disposable personal income real",
    "PCE":       "Personal consumption expenditures",
    "RRSFS":     "Retail sales food services",
}

def pull_fred():
    key = os.getenv("FRED_API_KEY", "")
    base = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    rows = []
    for sid, label in FRED_SERIES.items():
        try:
            url = f"{base}?id={sid}&vintage_date=&realtime_start=1980-01-01"
            if key:
                url += f"&api_key={key}"
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": "defensive-data-bot"})
            if r.status_code != 200:
                log(f"fred/{sid}", "fail", f"HTTP {r.status_code}")
                continue
            df = pd.read_csv(pd.io.common.StringIO(r.text))
            df.columns = ["date", "value"]
            df["series"] = sid
            df["label"] = label
            df = df[df["date"] >= "1980-01-01"]
            rows.append(df)
            log(f"fred/{sid}", "ok", f"{len(df)} rows")
        except Exception as e:
            log(f"fred/{sid}", "fail", str(e))
    if rows:
        save(pd.concat(rows, ignore_index=True), "fred_macro.csv")

# ── 5. Ken French factors 1980–today ────────────────────────────────────────
FRENCH_URLS = {
    "ff3_monthly": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
    "ff5_monthly": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "momentum":    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip",
    "49ind_monthly":"https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/49_Industry_Portfolios_CSV.zip",
}

def pull_french():
    import zipfile, io
    for name, url in FRENCH_URLS.items():
        try:
            r = requests.get(url, timeout=60,
                             headers={"User-Agent": "defensive-data-bot"})
            if r.status_code != 200:
                log(f"french/{name}", "fail", f"HTTP {r.status_code}")
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csv_name = [n for n in z.namelist() if n.endswith(".CSV") or n.endswith(".csv")][0]
            raw = z.read(csv_name).decode("latin-1").splitlines()
            # find header row (first line with comma-separated data)
            start = next(i for i, l in enumerate(raw)
                         if l.strip() and "," in l and not l.startswith(" "))
            df = pd.read_csv(pd.io.common.StringIO("\n".join(raw[start:])),
                             on_bad_lines="skip")
            df.columns = [c.strip() for c in df.columns]
            df = df.rename(columns={df.columns[0]: "date"})
            df["date"] = df["date"].astype(str).str.strip()
            # keep only rows that look like dates (6 or 8 digits)
            df = df[df["date"].str.match(r"^\d{6,8}$")]
            # filter to 1980+
            df = df[df["date"].str[:4].astype(int) >= 1980]
            save(df, f"french_{name}.csv")
        except Exception as e:
            log(f"french/{name}", "fail", str(e))

# ── 6. Crash-window summary: returns during each episode ────────────────────
def pull_crash_windows():
    try:
        prices = pd.read_csv("data/prices_daily.csv", parse_dates=["date"])
        crashes = pd.read_csv("data/crash_dates.csv")
        rows = []
        for _, c in crashes.iterrows():
            ep = str(c.get("episode", c.get("label", "")))
            peak = str(c.get("peak", ""))
            trough = str(c.get("trough", ""))
            if not peak or not trough:
                continue
            # 4-year recovery window
            rec_end = str(pd.to_datetime(trough) + pd.DateOffset(years=4))[:10]
            for col in [c for c in prices.columns if c != "date"]:
                try:
                    sub = prices[["date", col]].dropna()
                    p = sub[sub["date"] >= pd.to_datetime(peak)].iloc[0][col]
                    tr = sub[sub["date"] >= pd.to_datetime(trough)].iloc[0][col]
                    re = sub[sub["date"] >= pd.to_datetime(rec_end)]
                    r4 = re.iloc[0][col] if not re.empty else None
                    rows.append({
                        "episode": ep, "ticker": col,
                        "peak_price": p, "trough_price": tr,
                        "drawdown_pct": (tr - p) / p * 100 if p else None,
                        "recovery_4y_price": r4,
                        "recovery_4y_pct": (r4 - tr) / tr * 100 if r4 and tr else None,
                    })
                except Exception:
                    pass
        if rows:
            save(pd.DataFrame(rows), "crash_window_returns.csv")
    except Exception as e:
        log("crash_window_returns", "fail", str(e))

# ── 7. Write pull log ────────────────────────────────────────────────────────
def write_log():
    existing = Path("data/_pull_log.csv")
    new = pd.DataFrame(LOG)
    if existing.exists():
        old = pd.read_csv(existing)
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(existing, index=False)

# ── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== pull_defensive_data.py ===")
    pull_prices()
    pull_fundamentals()
    pull_financials()
    pull_fred()
    pull_french()
    pull_crash_windows()
    write_log()
    print("Done.")
