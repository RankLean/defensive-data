"""
Add-on pulls for the defensive-stocks project. Runs after pull_defensive_data.py.

  python pull_extensions.py --tickers tickers.txt --out data --ua "Your Name you@email.com"
  python pull_extensions.py --only edgar,options --tickers tickers.txt --out data --ua "..."

Modules: crashes, edgar, exposure, options, sentiment
Outputs (in --out):
  crash_dates.csv                verified S&P 500 / Nasdaq peaks and troughs
  edgar_facts_long.csv           every XBRL fact used, with filed date (point-in-time)
  edgar_quarterly.csv            quarterly panel, as_of = first filing date (no look-ahead)
  tech_exposure_text.csv         10-K keyword density for tech/AI demand
  tech_exposure_manual_TEMPLATE.csv  fill from segment notes; source URL required
  options_snapshot.csv           appended daily: ATM IV, 90% put skew, P/C OI and volume
  vol_indices.csv                ^VIX ^VIX9D ^VIX3M ^VVIX ^SKEW history
  sentiment_fred.csv             UMCSENT, NFCI, STLFSI4, USEPUINDXD, VIXCLS, BAA10Y
  cboe_putcall.csv               CBOE total/equity/index P/C (archive ends 2019)
  aaii_sentiment.csv             if the AAII file downloads; else logged
  _pull_log.csv                  status per source
Not financial advice.
"""
import argparse
import io
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    requests = None

LOG = []


def log(src, status, note=""):
    LOG.append({"source": src, "status": status, "note": str(note)[:300],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    print(f"[{status}] {src} {note}")


CRASHES = [
    # index, episode, peak_date, peak_close, trough_date, trough_close, tech_led, source
    ("^GSPC", "crash_1987", "1987-08-25", 336.77, "1987-12-04", 223.92, False, "Yardeni bull/bear tables"),
    ("^GSPC", "dotcom", "2000-03-24", 1527.46, "2002-10-09", 776.76, True, "Yardeni; crossingwallstreet"),
    ("^IXIC", "dotcom", "2000-03-10", 5048.62, "2002-10-09", 1114.11, True, "crossingwallstreet (peak); trough to confirm in data"),
    ("^GSPC", "gfc", "2007-10-09", 1565.15, "2009-03-09", 676.53, False, "Yardeni"),
    ("^GSPC", "covid", "2020-02-19", 3386.15, "2020-03-23", 2237.40, False, "Yardeni"),
    ("^GSPC", "bear_2022", "2022-01-03", 4796.56, "2022-10-12", 3577.03, True, "Yardeni; Motley Fool"),
    ("^IXIC", "bear_2022", "2021-11-19", 16057.44, "2022-12-28", 10213.29, True, "AP via KUTV (peak); Reuters (trough)"),
]


def pull_crashes(out):
    df = pd.DataFrame(CRASHES, columns=["index", "episode", "peak_date", "peak_close",
                                        "trough_date", "trough_close", "tech_led", "source"])
    df["drawdown"] = df.trough_close / df.peak_close - 1
    df.to_csv(out / "crash_dates.csv", index=False)
    log("crash_dates", "ok", f"{len(df)} rows; closing levels, not intraday")


def session(ua):
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    return s


def get(s, url, tries=3, pause=0.15, **kw):
    for i in range(tries):
        try:
            r = s.get(url, timeout=30, **kw)
            time.sleep(pause)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404):
                return r
        except Exception as e:
            err = e
        time.sleep(1.5 * (i + 1))
    return None


# ---------------- EDGAR ----------------
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "PremiumsEarnedNet", "HealthCareOrganizationRevenue"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividends_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "dps_declared": ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "total_assets": ["Assets"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "lt_debt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "medical_costs": ["BenefitsLossesAndExpenses", "PolicyholderBenefitsAndClaimsIncurredNet",
                      "LiabilityForFuturePolicyBenefitsPeriodExpense"],
}
STOCK_ITEMS = {"total_assets", "equity", "lt_debt", "cash"}
PER_SHARE = {"eps_diluted", "dps_declared"}


def cik_map(s):
    r = get(s, "https://www.sec.gov/files/company_tickers.json")
    if r is None or r.status_code != 200:
        raise RuntimeError("company_tickers.json not reachable")
    d = r.json()
    return {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in d.values()}


def facts_rows(tkr, js, key, names):
    rows = []
    for name in names:
        node = js.get("facts", {}).get("us-gaap", {}).get(name)
        if not node:
            continue
        for unit, arr in node.get("units", {}).items():
            for f in arr:
                if f.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "40-F"):
                    continue
                rows.append({"ticker": tkr, "item": key, "concept": name, "unit": unit,
                             "start": f.get("start"), "end": f.get("end"), "val": f.get("val"),
                             "form": f.get("form"), "filed": f.get("filed"),
                             "fy": f.get("fy"), "fp": f.get("fp"), "accn": f.get("accn")})
        if rows:
            break
    return rows


def to_quarterly(df, is_stock):
    """One value per fiscal period end. Flows: 3-month facts, Q4 = annual - 9M (or annual - Q1-Q3).
    Keeps the FIRST filing of each period so later restatements do not leak backwards."""
    if df.empty:
        return df
    df = df.copy()
    df["end"] = pd.to_datetime(df["end"])
    df["filed"] = pd.to_datetime(df["filed"])
    df = df.sort_values("filed")
    if is_stock:
        q = df.drop_duplicates("end", keep="first")[["end", "val", "filed"]]
        return q.rename(columns={"filed": "as_of"})
    df["start"] = pd.to_datetime(df["start"])
    df["days"] = (df["end"] - df["start"]).dt.days
    first = df.drop_duplicates(["start", "end"], keep="first")
    q3 = first[first.days.between(80, 100)][["start", "end", "val", "filed"]]
    m9 = first[first.days.between(260, 285)]
    fy = first[first.days.between(350, 380)]
    out = [q3]
    for _, a in fy.iterrows():
        if (q3.end == a.end).any():
            continue
        nine = m9[(m9.start == a.start)]
        if len(nine):
            n = nine.iloc[0]
            out.append(pd.DataFrame([{"start": n.end + pd.Timedelta(days=1), "end": a.end,
                                      "val": a.val - n.val, "filed": max(a.filed, n.filed)}]))
            continue
        qs = q3[(q3.start >= a.start) & (q3.end < a.end)]
        if len(qs) == 3:
            out.append(pd.DataFrame([{"start": qs.end.max() + pd.Timedelta(days=1), "end": a.end,
                                      "val": a.val - qs.val.sum(),
                                      "filed": max(a.filed, qs.filed.max())}]))
    q = pd.concat(out).drop_duplicates("end", keep="first").sort_values("end")
    return q[["end", "val", "filed"]].rename(columns={"filed": "as_of"})


def pull_edgar(out, tickers, ua):
    s = session(ua)
    try:
        cmap = cik_map(s)
    except Exception as e:
        log("edgar_tickers", "fail", e)
        return
    long_rows, panels = [], []
    for t in tickers:
        cik = cmap.get(t.upper())
        if cik is None:
            log(f"edgar:{t}", "skip", "no CIK (ETF, index or foreign)")
            continue
        r = get(s, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        if r is None or r.status_code != 200:
            log(f"edgar:{t}", "fail", getattr(r, "status_code", "no response"))
            continue
        js = r.json()
        tpanel = []
        for key, names in CONCEPTS.items():
            rows = facts_rows(t, js, key, names)
            long_rows += rows
            if not rows:
                continue
            q = to_quarterly(pd.DataFrame(rows), key in STOCK_ITEMS)
            if key in PER_SHARE and len(q):
                q = q[q.val.abs() < 1e4]
            tpanel.append(q.assign(item=key))
        if tpanel:
            p = pd.concat(tpanel)
            p["ticker"] = t
            panels.append(p)
            log(f"edgar:{t}", "ok", f"{p.item.nunique()} items, {p.end.nunique()} quarters")
    if long_rows:
        pd.DataFrame(long_rows).to_csv(out / "edgar_facts_long.csv", index=False)
    if panels:
        P = pd.concat(panels)
        wide = P.pivot_table(index=["ticker", "end"], columns="item", values="val", aggfunc="first")
        asof = P.groupby(["ticker", "end"]).as_of.max().rename("as_of")
        wide = wide.join(asof).reset_index()
        if {"medical_costs", "revenue"} <= set(wide.columns):
            wide["mlr_proxy"] = wide.medical_costs / wide.revenue
        wide.to_csv(out / "edgar_quarterly.csv", index=False)


# ---------------- tech exposure ----------------
TECH_TERMS = {
    "ai": r"\bartificial intelligence\b|\bgenerative ai\b|\bAI\b|\bmachine learning\b",
    "datacenter": r"\bdata ?cent(?:er|re)s?\b|\bhyperscal\w*",
    "semis": r"\bsemiconductor\w*\b|\bchips?\b|\bGPUs?\b",
    "cloud_software": r"\bcloud\b|\bsoftware\b|\bSaaS\b",
    "tech_customers": r"\btechnology (?:companies|customers|sector)\b",
}


def keyword_density(text):
    words = max(len(re.findall(r"\w+", text)), 1)
    res = {k: len(re.findall(p, text, flags=re.I if k != "ai" else 0)) for k, p in TECH_TERMS.items()}
    res = {f"{k}_per_10k_words": v / words * 1e4 for k, v in res.items()}
    res["words"] = words
    return res


def strip_html(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = re.sub(r"&nbsp;|&#160;", " ", h)
    return re.sub(r"\s+", " ", h)


def pull_exposure(out, tickers, ua):
    s = session(ua)
    try:
        cmap = cik_map(s)
    except Exception as e:
        log("exposure", "fail", e)
        return
    rows = []
    for t in tickers:
        cik = cmap.get(t.upper())
        if cik is None:
            continue
        r = get(s, f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if r is None or r.status_code != 200:
            log(f"exposure:{t}", "fail", "submissions")
            continue
        rec = r.json()["filings"]["recent"]
        f = pd.DataFrame(rec)
        f = f[f.form.isin(["10-K", "20-F", "40-F"])].sort_values("filingDate", ascending=False)
        for _, row in f.head(3).iterrows():
            acc = row.accessionNumber.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{row.primaryDocument}"
            d = get(s, url)
            if d is None or d.status_code != 200:
                log(f"exposure:{t}", "fail", url)
                continue
            kd = keyword_density(strip_html(d.text))
            rows.append({"ticker": t, "form": row.form, "filed": row.filingDate, "url": url, **kd})
        log(f"exposure:{t}", "ok", f"{min(3, len(f))} annual reports")
    if rows:
        pd.DataFrame(rows).to_csv(out / "tech_exposure_text.csv", index=False)
    pd.DataFrame({"ticker": tickers, "fiscal_year": "", "tech_customer_revenue_share": "",
                  "ai_capex_linked_revenue_share": "", "basis": "", "source_url": "",
                  "page_or_note": ""}).to_csv(out / "tech_exposure_manual_TEMPLATE.csv", index=False)


# ---------------- options ----------------
def chain_metrics(calls, puts, spot, dte):
    """calls/puts: DataFrames with strike, impliedVolatility, openInterest, volume."""
    m = {"spot": spot, "dte": dte}
    for side, df in (("c", calls), ("p", puts)):
        df = df.dropna(subset=["impliedVolatility"])
        df = df[(df.impliedVolatility > 0.01) & (df.impliedVolatility < 5)]
        if side == "c":
            c = df
        else:
            p = df
    if c.empty or p.empty:
        return m
    atm_c = c.iloc[(c.strike - spot).abs().argsort()[:1]].impliedVolatility.iloc[0]
    atm_p = p.iloc[(p.strike - spot).abs().argsort()[:1]].impliedVolatility.iloc[0]
    m["atm_iv"] = (atm_c + atm_p) / 2
    p90 = p.iloc[(p.strike - 0.9 * spot).abs().argsort()[:1]]
    m["put90_iv"] = p90.impliedVolatility.iloc[0]
    m["put90_strike"] = p90.strike.iloc[0]
    m["skew_90_atm"] = m["put90_iv"] - m["atm_iv"]
    c110 = c.iloc[(c.strike - 1.1 * spot).abs().argsort()[:1]]
    m["call110_iv"] = c110.impliedVolatility.iloc[0]
    oi_c, oi_p = calls.openInterest.fillna(0).sum(), puts.openInterest.fillna(0).sum()
    v_c, v_p = calls.volume.fillna(0).sum(), puts.volume.fillna(0).sum()
    m["pc_oi"] = oi_p / oi_c if oi_c else np.nan
    m["pc_vol"] = v_p / v_c if v_c else np.nan
    return m


def pull_options(out, tickers, target_dte=30):
    try:
        import yfinance as yf
    except ImportError:
        log("options", "fail", "pip install yfinance")
        return
    today = date.today()
    rows = []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            exps = tk.options
            if not exps:
                log(f"options:{t}", "skip", "no listed options")
                continue
            dtes = [(e, (pd.Timestamp(e).date() - today).days) for e in exps]
            dtes = [x for x in dtes if x[1] >= 7]
            e, dte = min(dtes, key=lambda x: abs(x[1] - target_dte))
            ch = tk.option_chain(e)
            spot = tk.history(period="5d").Close.dropna().iloc[-1]
            rows.append({"snapshot_date": today.isoformat(), "ticker": t, "expiry": e,
                         **chain_metrics(ch.calls, ch.puts, float(spot), dte)})
            log(f"options:{t}", "ok", e)
        except Exception as ex:
            log(f"options:{t}", "fail", ex)
        time.sleep(0.5)
    if rows:
        f = out / "options_snapshot.csv"
        new = pd.DataFrame(rows)
        if f.exists():
            new = pd.concat([pd.read_csv(f), new]).drop_duplicates(["snapshot_date", "ticker"], keep="last")
        new.to_csv(f, index=False)
    try:
        v = yf.download(["^VIX", "^VIX9D", "^VIX3M", "^VVIX", "^SKEW"], start="1990-01-01",
                        auto_adjust=False, progress=False)["Close"]
        v["vix_term_ratio"] = v["^VIX"] / v["^VIX3M"]
        v.to_csv(out / "vol_indices.csv")
        log("vol_indices", "ok", f"{v.index.min().date()} to {v.index.max().date()}")
    except Exception as ex:
        log("vol_indices", "fail", ex)


# ---------------- sentiment ----------------
FRED_SENT = {"UMCSENT": "UMich consumer sentiment (monthly)",
             "NFCI": "Chicago Fed financial conditions (weekly)",
             "STLFSI4": "St Louis Fed financial stress (weekly)",
             "USEPUINDXD": "Economic policy uncertainty (daily)",
             "VIXCLS": "VIX close (daily)",
             "BAA10Y": "Moody's Baa minus 10y (daily)"}
CBOE_PC = {"total": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv",
           "equity": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv",
           "index": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/indexpc.csv"}
AAII_URL = "https://www.aaii.com/files/surveys/sentiment.xls"


def read_cboe_pc(text):
    lines = text.splitlines()
    hdr = next(i for i, l in enumerate(lines) if re.match(r"(?i)^\s*(trade_)?date", l))
    df = pd.read_csv(io.StringIO("\n".join(lines[hdr:])))
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    dcol = df.columns[0]
    df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
    return df.dropna(subset=[dcol]).rename(columns={dcol: "date"})


def pull_sentiment(out, ua):
    s = session(ua)
    fr = []
    for sid, desc in FRED_SENT.items():
        r = get(s, f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}")
        if r is None or r.status_code != 200:
            log(f"fred:{sid}", "fail", getattr(r, "status_code", "no response"))
            continue
        d = pd.read_csv(io.StringIO(r.text))
        d.columns = ["date", sid]
        d["date"] = pd.to_datetime(d.date)
        d[sid] = pd.to_numeric(d[sid], errors="coerce")
        fr.append(d.set_index("date"))
        log(f"fred:{sid}", "ok", desc)
    if fr:
        pd.concat(fr, axis=1).sort_index().to_csv(out / "sentiment_fred.csv")
    pcs = []
    for k, url in CBOE_PC.items():
        r = get(s, url)
        if r is None or r.status_code != 200:
            log(f"cboe_pc:{k}", "fail", getattr(r, "status_code", "no response"))
            continue
        try:
            d = read_cboe_pc(r.text)
            pcs.append(d.assign(series=k))
            log(f"cboe_pc:{k}", "ok", f"to {d.date.max().date()}")
        except Exception as ex:
            log(f"cboe_pc:{k}", "fail", ex)
    if pcs:
        pd.concat(pcs).to_csv(out / "cboe_putcall.csv", index=False)
    r = get(s, AAII_URL, headers={"Referer": "https://www.aaii.com/sentimentsurvey"})
    if r is not None and r.status_code == 200 and r.content[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04"):
        try:
            x = pd.read_excel(io.BytesIO(r.content), skiprows=3)
            x = x.rename(columns={x.columns[0]: "date"})
            x["date"] = pd.to_datetime(x.date, errors="coerce")
            x.dropna(subset=["date"]).to_csv(out / "aaii_sentiment.csv", index=False)
            log("aaii", "ok")
        except Exception as ex:
            log("aaii", "fail", f"parse: {ex} (needs xlrd for .xls)")
    else:
        log("aaii", "fail", "blocked or HTML; download sentiment.xls manually while logged in")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="file, one ticker per line")
    ap.add_argument("--out", default="data")
    ap.add_argument("--ua", required=True, help='SEC requires "Name email"')
    ap.add_argument("--only", default="crashes,edgar,exposure,options,sentiment")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tickers = [l.strip().upper() for l in Path(a.tickers).read_text().splitlines()
               if l.strip() and not l.startswith("#")]
    mods = set(a.only.split(","))
    if "crashes" in mods:
        pull_crashes(out)
    if requests is None:
        log("network", "fail", "pip install requests")
    else:
        if "edgar" in mods:
            pull_edgar(out, tickers, a.ua)
        if "exposure" in mods:
            pull_exposure(out, tickers, a.ua)
        if "sentiment" in mods:
            pull_sentiment(out, a.ua)
    if "options" in mods:
        pull_options(out, tickers)
    pd.DataFrame(LOG).to_csv(out / "_pull_log.csv", index=False)


if __name__ == "__main__":
    main()
