"""Download daily close prices for the portfolio from Kite or IBKR, for /analytics to read.

Run it yourself from the repo root, in an environment with the quant repo's
dependencies (personal_projects has them):

    python scripts/refresh_prices.py --source ibkr_live               # IBKR, live TWS (port 7496)
    python scripts/refresh_prices.py --source ibkr_paper              # IBKR, paper TWS (port 7497)
    python scripts/refresh_prices.py --source kite                    # Kite Connect (daily login)
    python scripts/refresh_prices.py --source ibkr_live --cache-only  # no connection: IBKR bars already stored

The fetching is done by quant_risk_and_trading_portfolio's own price code
(--quant-repo, or the QUANT_REPO variable), so logins, the IBKR cache and
symbol mapping live in one place. Market data only: nothing here places or
modifies orders. Prices go through that repo's validation, then the last
--sessions sessions are written to data/prices_<source>.csv, with
data/prices_<source>.json recording where they came from. Both files are
gitignored: they are exchange data obtained under your own data agreements.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from argparse import ArgumentParser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from portfolio import PORTFOLIO  # noqa: E402
from prices import MARKET_SOURCES, snapshot_path  # noqa: E402

DEFAULT_QUANT_REPO = Path(r"D:\Personal_projects\quant_risk_and_trading_portfolio")
SESSIONS = 260  # the same history length as the synthetic file
MAX_FILL_SESSIONS = 1  # as in the quant repo: one no-trade session is carried forward, longer gaps stop the run
DESCRIPTIONS = {
    "kite": "Kite Connect daily closes",
    "ibkr_paper": "IBKR daily closes (paper account; adjusted for splits and bonus issues, not dividends)",
    "ibkr_live": "IBKR daily closes (live account, market data only; adjusted for splits and bonus issues, not dividends)",
}


def fetch(source: str, start: str, end: str, cache_only: bool):  # -> pandas.DataFrame
    """Close prices from the quant repo's code, the same way its run_report.py does it."""
    if source == "kite":
        if cache_only:
            raise SystemExit("--cache-only applies to IBKR sources; Kite prices are not cached.")
        from shared.data import fetch_price_data

        return fetch_price_data(PORTFOLIO.tickers, start, end)
    from data_providers.ibkr_prices import build_close_prices, fetch_ibkr_price_data

    environment = source.removeprefix("ibkr_")
    if cache_only:
        return build_close_prices(PORTFOLIO.tickers, start, end, environment=environment)
    return fetch_ibkr_price_data(PORTFOLIO.tickers, start, end, environment=environment)


def main() -> None:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=MARKET_SOURCES, required=True)
    parser.add_argument("--end", default=date.today().isoformat(), help="last date YYYY-MM-DD (default: today)")
    parser.add_argument("--cache-only", action="store_true", help="IBKR only: use stored bars, do not connect to TWS")
    parser.add_argument("--sessions", type=int, default=SESSIONS)
    parser.add_argument("--quant-repo", type=Path, default=Path(os.environ.get("QUANT_REPO", DEFAULT_QUANT_REPO)))
    args = parser.parse_args()

    if not (args.quant_repo / "data_providers").is_dir():
        raise SystemExit(f"Quant repo not found at {args.quant_repo}; pass --quant-repo or set QUANT_REPO.")
    sys.path.insert(0, str(args.quant_repo))
    from shared.validation import validate_close_prices

    # About 1.6 calendar days per NSE session, plus slack for holidays.
    start = (date.fromisoformat(args.end) - timedelta(days=int(args.sessions * 1.6) + 30)).isoformat()
    print(f"Fetching {len(PORTFOLIO.tickers)} tickers {start} to {args.end} from {args.source}"
          f"{' (stored bars only)' if args.cache_only else ''}...")
    prices = fetch(args.source, start, args.end, args.cache_only)
    prices = validate_close_prices(prices, PORTFOLIO.tickers, max_fill_sessions=MAX_FILL_SESSIONS)
    prices = prices[list(PORTFOLIO.tickers)].tail(args.sessions)
    if len(prices) < args.sessions:
        raise SystemExit(f"Only {len(prices)} sessions available; need {args.sessions}.")
    prices.index = prices.index.strftime("%Y-%m-%d")
    prices.index.name = "date"

    out = snapshot_path(args.source)
    prices.to_csv(out, lineterminator="\n")
    quant_commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=args.quant_repo,
                                  capture_output=True, text=True).stdout.strip()
    meta = {
        "source": args.source, "description": DESCRIPTIONS[args.source],
        "first_session": prices.index[0], "last_session": prices.index[-1], "sessions": len(prices),
        "requested_end": args.end, "cache_only": args.cache_only,
        # With --cache-only this is when the file was assembled, not when the bars were downloaded.
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quant_repo_commit": quant_commit, "file": out.name,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {out.relative_to(ROOT)}: {len(prices)} sessions, {meta['first_session']} to {meta['last_session']}")


if __name__ == "__main__":
    main()
