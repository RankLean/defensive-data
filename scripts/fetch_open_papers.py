"""Download open-access PDFs listed in papers.csv (columns: id,url,note). Skips files already present."""
import argparse
import csv
import time
from pathlib import Path

import requests

UA = "Mozilla/5.0 (research data pull; contact in repo README)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="papers.csv")
    ap.add_argument("--out", default="papers")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    log = []
    for row in csv.DictReader(open(a.list)):
        f = out / f"{row['id']}.pdf"
        if f.exists() and f.stat().st_size > 10_000:
            log.append((row["id"], "cached"))
            continue
        try:
            r = requests.get(row["url"], headers={"User-Agent": UA}, timeout=60)
            ok = r.status_code == 200 and r.content[:4] == b"%PDF"
            if ok:
                f.write_bytes(r.content)
            log.append((row["id"], "ok" if ok else f"fail {r.status_code} {r.headers.get('content-type', '')}"))
        except Exception as e:
            log.append((row["id"], f"fail {e}"))
        time.sleep(1)
    with open(out / "_papers_log.csv", "w", newline="") as fh:
        csv.writer(fh).writerows([("id", "status"), *log])
    for x in log:
        print(*x)


if __name__ == "__main__":
    main()
