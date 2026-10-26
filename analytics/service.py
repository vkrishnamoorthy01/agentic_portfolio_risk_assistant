"""Deterministic portfolio analytics tool, exposed over HTTP for Make.

This is the "Python = deterministic computation" layer of the architecture:
the LLM never does this arithmetic itself, it only calls /analytics and
narrates the numbers it gets back.

The numbers come from a daily close-price file chosen by prices.py: Kite,
IBKR paper or IBKR live prices downloaded by scripts/refresh_prices.py, or
the synthetic data/mock_prices.csv. The default, "latest", is the most
recent download. Every /analytics response names the source
("data_source"), carries the file's last date ("as_of") and says how to
fetch newer prices, so nothing downstream can present stale data as live.

Bad inputs fail loudly: a missing price, a ticker missing from the file or
inconsistent weights return a 500 with the reason, never a number computed
from incomplete data. Requests are logged (method, path, status, time);
query text is not.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from portfolio import PORTFOLIO
from prices import (
    SOURCE_CHOICES, UnknownSourceError, available_sources, data_note, default_source, resolve_source, snapshot_path,
)
from retrieval import MAX_QUERY_CHARS, POLICY_VERSION, InvalidQueryError, policy_section_count, retrieve, warm_up
from var_models import InvalidInputError, historical_var, portfolio_returns

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("portfolio_service")

VOL_WINDOW_DAYS = 20
VAR_CONFIDENCE = 0.99


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Loading the embedding model takes a few seconds and most of the memory;
    # doing it at startup (when asked) keeps the first /policy request fast.
    if os.environ.get("RETRIEVAL_WARM_UP", "0") == "1":
        started = time.perf_counter()
        warm_up()
        logger.info("retrieval model loaded in %.1fs", time.perf_counter() - started)
    yield


app = FastAPI(title="Portfolio Analytics Tool", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "%s %s -> %d in %.0f ms",
        request.method, request.url.path, response.status_code, (time.perf_counter() - started) * 1000,
    )
    return response


@app.exception_handler(InvalidInputError)
async def invalid_input(request: Request, exc: InvalidInputError) -> JSONResponse:
    logger.error("analytics input check failed on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"error": "invalid analytics input", "detail": str(exc)})


@app.exception_handler(UnknownSourceError)
async def unknown_source(request: Request, exc: UnknownSourceError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "price source unavailable", "detail": str(exc)})


@app.exception_handler(InvalidQueryError)
async def invalid_query(request: Request, exc: InvalidQueryError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "invalid policy query", "detail": str(exc)})


def load_prices(path: Path) -> pd.DataFrame:
    """Load daily close prices, one column per ticker, and check them."""
    prices = pd.read_csv(path, index_col="date", parse_dates=True)
    missing = [t for t in PORTFOLIO.tickers if t not in prices.columns]
    if missing:
        raise InvalidInputError(f"Price file has no column for {missing}.")
    prices = prices[list(PORTFOLIO.tickers)]
    if len(prices) < VOL_WINDOW_DAYS + 1:
        raise InvalidInputError(f"Price file has {len(prices)} rows; need at least {VOL_WINDOW_DAYS + 1}.")
    if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise InvalidInputError("Price file dates are out of order or duplicated.")
    values = prices.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        bad = prices.columns[~(np.isfinite(values) & (values > 0)).all(axis=0)].tolist()
        raise InvalidInputError(f"Missing, non-finite or non-positive prices for {bad}.")
    return prices


@app.get("/health")
def health() -> dict:
    # Render sets RENDER_GIT_COMMIT to the deployed commit, so this shows which
    # version is live; "local" when run outside Render.
    return {"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "local")}


@app.get("/analytics")
def get_analytics(source: str | None = Query(None, description=f"one of {list(SOURCE_CHOICES)}; default latest")) -> dict:
    """Compute the portfolio risk snapshot: returns, vol, VaR, concentration,
    top contributors/detractors, the numbers a risk analyst would check
    before answering "has anything breached a limit today?"
    """
    requested = source or default_source()
    resolved = resolve_source(requested)
    prices = load_prices(snapshot_path(resolved))
    returns = prices.pct_change().iloc[1:]  # prices are checked complete, so no row is dropped
    weights = PORTFOLIO.weights
    port_rets = portfolio_returns(returns, weights)

    last_return = port_rets.iloc[-1]
    vol_recent = port_rets.tail(VOL_WINDOW_DAYS).std() * np.sqrt(252)
    var_99 = historical_var(port_rets, confidence_level=VAR_CONFIDENCE, notional=PORTFOLIO.notional)

    nav_curve = (1 + port_rets).cumprod()
    drawdown_from_peak = (nav_curve / nav_curve.cummax() - 1).iloc[-1]

    last_day_contrib = returns.iloc[-1].mul(weights).sort_values(ascending=False)

    # All percentage-like fields below are scaled to percentage POINTS
    # (e.g. 2.11, not 0.0211) so a literal "%" can always be appended
    # after them without any caller having to guess or convert units.
    return {
        "as_of": str(prices.index[-1].date()),
        "data_source": resolved,
        "requested_source": requested,
        "data_note": data_note(resolved, requested),
        "downloaded_sources": available_sources(),
        "notional": PORTFOLIO.notional,
        "portfolio_return_1d_pct": round(float(last_return) * 100, 2),
        "vol_20d_annualized_pct": round(float(vol_recent) * 100, 2),
        "historical_var_99_1d": {
            "amount": round(float(var_99), 2),
            "pct_of_nav_pct": round(float(var_99 / PORTFOLIO.notional) * 100, 2),
        },
        "drawdown_from_peak_pct": round(float(drawdown_from_peak) * 100, 2),
        "largest_position_pct": round(float(weights.max()) * 100, 2),
        "individual_returns_1d_pct": (returns.iloc[-1] * 100).round(2).to_dict(),
        "top_contributors_1d_pct": (last_day_contrib.head(3) * 100).round(2).to_dict(),
        "top_detractors_1d_pct": (last_day_contrib.tail(3) * 100).round(2).to_dict(),
    }


@app.get("/policy")
def get_policy(
    query: str = Query(..., min_length=1, max_length=MAX_QUERY_CHARS),
    top_k: int = Query(2, ge=1),
    include_core: bool = Query(False, description="also return the core limit and escalation clauses"),
) -> dict:
    """Retrieve the policy sections most relevant to a natural-language query.

    e.g. /policy?query=has the portfolio breached any risk limits&include_core=true
    """
    if top_k > policy_section_count():
        raise InvalidQueryError(f"top_k must be between 1 and {policy_section_count()}, got {top_k}.")
    results = retrieve(query, top_k=top_k, include_core=include_core)
    logger.info("policy query: %d chars, top_k=%d, include_core=%s, top section=%r",
                len(query), top_k, include_core, results[0]["section"])
    return {"query": query, "policy_version": POLICY_VERSION, "include_core": include_core, "results": results}
