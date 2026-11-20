# defensive-data

GitHub Actions pulls the data for the defensive-stocks project and commits it here. Claude reads the repo directly. Not financial advice.

## Setup (once, ~10 min, phone OK)

1. github.com → New repository → name `defensive-data` → **Private** → Create.
2. Add file → Upload files → drag in everything from this folder (keep the `.github/workflows` and `scripts` folders).
3. Add your own `scripts/pull_defensive_data.py`. Edit `tickers.txt` to your list.
4. Settings → Secrets and variables → Actions → New repository secret:
   - `SEC_UA` = `Your Name your@email.com` (SEC requires it)
   - `FRED_API_KEY` = your FRED key (only if your main script uses one)
5. Settings → Actions → General → Workflow permissions → **Read and write** → Save.
6. Actions tab → `pull-data` → Run workflow.

## Inbox

Drop any file into `inbox/` (GitHub app: Add file → Upload). A push there refreshes `MANIFEST.md` in ~1 min. Claude reads it from the repo.

## Schedule

- Weekdays 21:37 UTC (after US close): options snapshot only (builds IV/skew history).
- Fridays and manual runs: everything.
- Manual runs also download the open-access papers in `papers.csv`.

## Sharing with Claude

Tell Claude the repo name (`your-github-username/defensive-data`). Claude attaches it read-only and starts from `MANIFEST.md`, which lists every file, row count, date range and failed pull.

## Limits

- GitHub blocks files >100 MB. Split or gzip big price files.
- Paywalled papers and bank portals: download yourself if your access terms allow, and upload to `papers/`. Many bank research terms forbid feeding notes to AI tools; check first.
- yfinance is unofficial and can break or rate-limit. Failures land in `data/_pull_log.csv` and `MANIFEST.md`.
