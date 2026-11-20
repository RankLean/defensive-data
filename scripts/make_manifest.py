"""Write MANIFEST.md: every file in data/ and papers/ with size, rows, columns, date range. Lets Claude see what's there fast."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

lines = [f"# Manifest\n\nGenerated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n",
         "| file | KB | rows | cols | first | last |", "|---|---|---|---|---|---|"]
for p in sorted(Path("data").rglob("*")):
    if not p.is_file() or p.name.startswith("."):
        continue
    kb = p.stat().st_size // 1024
    rows = cols = first = last = ""
    if p.suffix == ".csv":
        try:
            df = pd.read_csv(p, low_memory=False)
            rows, cols = len(df), len(df.columns)
            dcol = next((c for c in df.columns if str(c).lower() in ("date", "end", "snapshot_date", "unnamed: 0")), None)
            if dcol is not None:
                d = pd.to_datetime(df[dcol], errors="coerce").dropna()
                if len(d):
                    first, last = d.min().date(), d.max().date()
        except Exception as e:
            rows = f"unreadable: {e}"[:60]
    lines.append(f"| {p} | {kb} | {rows} | {cols} | {first} | {last} |")
pp = [p for p in sorted(Path("papers").glob("*.pdf"))]
lines += ["", f"## papers ({len(pp)})", *[f"- {p.name} ({p.stat().st_size // 1024} KB)" for p in pp]]
ib = [p for p in sorted(Path("inbox").rglob("*")) if p.is_file() and not p.name.startswith(".") and p.name != "README.md"]
lines += ["", f"## inbox ({len(ib)})", *[f"- {p.relative_to('inbox')} ({p.stat().st_size // 1024} KB)" for p in ib]]
for log in ("data/_pull_log.csv", "papers/_papers_log.csv"):
    if Path(log).exists():
        df = pd.read_csv(log)
        bad = df[~df.iloc[:, 1].astype(str).str.startswith(("ok", "cached"))]
        lines += ["", f"## failures in {log} ({len(bad)})", *[f"- {' | '.join(map(str, r))}" for r in bad.values]]
Path("MANIFEST.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines[:40]))
