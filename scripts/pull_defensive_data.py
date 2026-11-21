"""
pull_defensive_data.py
Pulls: prices + fundamentals (yfinance), Ken French factors,
FRED macro series, analyst estimates (yfinance), annual market
outlook summaries (public PDFs where available),
corporate bond / credit data, and lead-lag analysis
(bond spread widening vs subsequent stock drawdowns by sector).
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
    "BAMLH0A0HYM2": "HY OAS spread (all sectors)",
    "BAA10Y":    "BAA-10y credit spread",
    # sector credit spreads (ICE BofA indices via FRED)
    "BAMLC0A1CAAA": "IG AAA OAS",
    "BAMLC0A2CAA":  "IG AA OAS",
    "BAMLC0A3CA":   "IG A OAS",
    "BAMLC0A4CBBB": "IG BBB OAS",
    "BAMLH0A1HYBB": "HY BB OAS",
    "BAMLH0A2HYB":  "HY B OAS",
    "BAMLH0A3HYC":  "HY CCC OAS",
    # sector-specific IG spreads (ICE BofA)
    "BAMLC2A0C35Y":  "IG 3-5yr OAS",
    "BAMLEMHBHYCRPIOAS": "EM HY corporate OAS",
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
            start = next(i for i, l in enumerate(raw)
                         if l.strip() and "," in l and not l.startswith(" "))
            df = pd.read_csv(pd.io.common.StringIO("\n".join(raw[start:])),
                             on_bad_lines="skip")
            df.columns = [c.strip() for c in df.columns]
            df = df.rename(columns={df.columns[0]: "date"})
            df["date"] = df["date"].astype(str).str.strip()
            df = df[df["date"].str.match(r"^\d{6,8}$")]
            df = df[df["date"].str[:4].astype(int) >= 1980]
            save(df, f"french_{name}.csv")
        except Exception as e:
            log(f"french/{name}", "fail", str(e))

# ── 6. Corporate bond data per ticker (yfinance) ────────────────────────────
# Maps our tickers to their GICS sector for grouping
TICKER_SECTOR = {
    "UNH": "Health Care", "ELV": "Health Care", "CNC": "Health Care",
    "MOH": "Health Care", "CI":  "Health Care", "HUM": "Health Care",
    "CVS": "Health Care", "OSCR":"Health Care",
    "WM":  "Industrials", "RSG": "Industrials",
    "COST":"Consumer Staples", "WMT":"Consumer Staples",
    "PG":  "Consumer Staples", "KO": "Consumer Staples", "PEP":"Consumer Staples",
    "JNJ": "Health Care", "ABBV":"Health Care",
    "DUK": "Utilities", "SO":  "Utilities", "NEE": "Utilities",
}

def pull_bond_info():
    """
    Pull per-ticker bond/debt info from yfinance:
    - Credit rating proxy: interest coverage, debt/equity, debt/EBITDA
    - Bond ETF prices as sector credit proxies (LQD, HYG, plus sector ETFs)
    - FRED sector OAS spreads already in fred_macro.csv
    """
    # Bond proxy ETFs: sector investment grade + high yield
    bond_etfs = {
        "LQD":  "IG Corporate Bond ETF",
        "HYG":  "HY Corporate Bond ETF",
        "JNK":  "HY Bond ETF (SPDR)",
        "VCSH": "Short-Term Corporate Bond ETF",
        "VCIT": "Intermediate Corporate Bond ETF",
        "VCLT": "Long-Term Corporate Bond ETF",
        # Sector bond ETFs
        "FHLC": "Health Care Bond proxy (Fidelity HC ETF)",
        "XLU":  "Utilities sector ETF (bond-like)",
        "KBWB": "Bank bond proxy",
        "IGIB": "IG Intermediate Corporate",
        "IGSB": "IG Short-Term Corporate",
        # Treasury benchmarks for spread calculation
        "SHY":  "1-3yr Treasury",
        "IEF":  "7-10yr Treasury",
        "TLT":  "20+yr Treasury",
    }

    # Pull bond ETF prices (from 1990 where available)
    syms = sorted(bond_etfs.keys())
    try:
        raw = yf.download(syms, start="1990-01-01", auto_adjust=True,
                          progress=False, threads=True)
        close = raw["Close"].reset_index()
        close.columns.name = None
        close = close.rename(columns={"Date": "date"})
        close["date"] = pd.to_datetime(close["date"]).dt.date.astype(str)
        save(close, "bond_etf_prices.csv")

        # Save ETF metadata
        meta = pd.DataFrame([{"ticker": k, "description": v}
                              for k, v in bond_etfs.items()])
        save(meta, "bond_etf_metadata.csv")
    except Exception as e:
        log("bond_etf_prices", "fail", str(e))

    # Pull per-ticker debt metrics from yfinance info
    rows = []
    for sym in tickers():
        try:
            tk = yf.Ticker(sym)
            info = tk.info or {}
            # Debt service metrics — credit quality proxies
            ebitda = info.get("ebitda") or 0
            total_debt = info.get("totalDebt") or 0
            interest_exp = info.get("interestExpense") or None
            ebit = info.get("ebit") or None
            rows.append({
                "ticker": sym,
                "as_of": date.today().isoformat(),
                "sector": TICKER_SECTOR.get(sym, info.get("sector", "")),
                "total_debt": total_debt,
                "total_cash": info.get("totalCash"),
                "net_debt": total_debt - (info.get("totalCash") or 0),
                "debt_to_equity": info.get("debtToEquity"),
                "debt_to_ebitda": (total_debt / ebitda) if ebitda else None,
                "interest_expense": interest_exp,
                "interest_coverage": (ebit / abs(interest_exp))
                    if ebit and interest_exp and interest_exp != 0 else None,
                "current_ratio": info.get("currentRatio"),
                "quick_ratio": info.get("quickRatio"),
                "bond_rating_proxy": _rating_proxy(
                    info.get("debtToEquity"), ebitda, total_debt,
                    ebit, interest_exp),
            })
        except Exception as e:
            log(f"bond_info/{sym}", "fail", str(e))
    if rows:
        save(pd.DataFrame(rows), "bond_credit_metrics.csv")

def _rating_proxy(de, ebitda, debt, ebit, interest_exp):
    """
    Rough proxy for credit quality bucket based on public rules-of-thumb.
    Returns: AAA/AA/A/BBB/BB/B/CCC or Unknown
    """
    try:
        cov = (ebit / abs(interest_exp)) if ebit and interest_exp else None
        d_ebitda = (debt / ebitda) if ebitda and debt else None
        if cov and cov > 12 and d_ebitda and d_ebitda < 1.5:
            return "AAA/AA"
        elif cov and cov > 7 and d_ebitda and d_ebitda < 2.5:
            return "A"
        elif cov and cov > 4 and d_ebitda and d_ebitda < 3.5:
            return "BBB"
        elif cov and cov > 2:
            return "BB"
        elif cov and cov > 1:
            return "B"
        elif cov and cov <= 1:
            return "CCC"
        return "Unknown"
    except Exception:
        return "Unknown"

# ── 7. Bond-to-stock lead-lag analysis ──────────────────────────────────────
def pull_bond_leadlag():
    """
    Tests whether credit spread widening leads stock drawdowns.
    Uses FRED OAS series (from fred_macro.csv) vs sector ETF prices.
    Computes: for each 1-month spread widening event, what was the
    average sector ETF return over the next 1, 3, 6, 12 months.
    Also computes by industry (from fundamentals_snapshot.csv).
    """
    try:
        fred = pd.read_csv("data/fred_macro.csv", parse_dates=["date"])
        prices = pd.read_csv("data/prices_daily.csv", parse_dates=["date"])
    except Exception as e:
        log("bond_leadlag", "fail", f"missing input files: {e}")
        return

    # Sector ETF mapping
    sector_etfs = {
        "Health Care":      "XLV",
        "Consumer Staples": "XLP",
        "Utilities":        "XLU",
        "Energy":           "XLE",
        "Financials":       "XLF",
        "Technology":       "XLK",
        "Industrials":      "XLI",
        "Materials":        "XLB",
        "Real Estate":      "XLRE",
        "Communication":    "XLC",
        "Consumer Disc":    "XLY",
        "Broad Market":     "SPY",
    }

    # Spread series to test
    spread_series = {
        "IG_OAS":  "BAMLC0A4CBBB",   # BBB as IG proxy
        "HY_OAS":  "BAMLH0A0HYM2",   # All HY
        "BAA_10Y": "BAA10Y",
    }

    rows = []
    horizons = [21, 63, 126, 252]  # trading days: 1m, 3m, 6m, 12m

    for spread_name, fred_id in spread_series.items():
        try:
            spread = fred[fred["series"] == fred_id][["date", "value"]].dropna()
            spread = spread.sort_values("date").reset_index(drop=True)
            spread["value"] = pd.to_numeric(spread["value"], errors="coerce")
            spread["chg_1m"] = spread["value"].diff(21)  # ~1 month change

            # Identify widening events: top quartile of monthly spread increases
            threshold = spread["chg_1m"].quantile(0.75)
            events = spread[spread["chg_1m"] >= threshold]["date"].tolist()

            for sector, etf in sector_etfs.items():
                if etf not in prices.columns:
                    continue
                px = prices[["date", etf]].dropna().sort_values("date")

                for event_date in events:
                    try:
                        # Find price at event
                        after = px[px["date"] >= event_date]
                        if after.empty:
                            continue
                        p0 = after.iloc[0][etf]
                        p0_date = after.iloc[0]["date"]

                        for h in horizons:
                            future = px[px["date"] >= p0_date].iloc[h:h+1]
                            if future.empty:
                                continue
                            ph = future.iloc[0][etf]
                            ret = (ph - p0) / p0 * 100
                            rows.append({
                                "spread_series": spread_name,
                                "sector": sector,
                                "etf": etf,
                                "event_date": str(event_date)[:10],
                                "horizon_days": h,
                                "horizon_label": {21:"1m",63:"3m",126:"6m",252:"12m"}[h],
                                "spread_widening_bps": round(
                                    spread[spread["date"] == event_date]["chg_1m"].values[0] * 100, 1)
                                    if len(spread[spread["date"] == event_date]) else None,
                                "fwd_return_pct": round(ret, 2),
                            })
                    except Exception:
                        pass
        except Exception as e:
            log(f"bond_leadlag/{spread_name}", "fail", str(e))

    if rows:
        df = pd.DataFrame(rows)
        save(df, "bond_leadlag_raw.csv")

        # Summarise: average forward return by spread_series × sector × horizon
        summary = (df.groupby(["spread_series", "sector", "etf", "horizon_label"])
                     ["fwd_return_pct"]
                     .agg(["mean", "median", "std", "count"])
                     .reset_index()
                     .rename(columns={"mean": "avg_fwd_return_pct",
                                      "median": "median_fwd_return_pct",
                                      "std": "std_fwd_return_pct",
                                      "count": "n_events"}))
        summary["avg_fwd_return_pct"] = summary["avg_fwd_return_pct"].round(2)
        summary["median_fwd_return_pct"] = summary["median_fwd_return_pct"].round(2)
        summary["std_fwd_return_pct"] = summary["std_fwd_return_pct"].round(2)
        save(summary, "bond_leadlag_summary.csv")
        log("bond_leadlag_summary", "ok",
            f"{len(summary)} rows — avg fwd returns by sector × horizon after spread widening")

# ── 8. Crash-window summary ──────────────────────────────────────────────────
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

# ── 9. Write pull log ────────────────────────────────────────────────────────
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
    log("pull_defensive_data", "started", f"python {sys.version.split()[0]}")
    pull_prices()
    pull_fundamentals()
    pull_financials()
    pull_fred()
    pull_french()
    pull_bond_info()
    pull_bond_leadlag()
    pull_crash_windows()
    write_log()
    print("Done.")
