"""Checks on the portfolio definition and the price file the /analytics endpoint reads."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from portfolio import PORTFOLIO
from var_models import historical_var, portfolio_returns

PRICES = Path(__file__).resolve().parent.parent / "data" / "mock_prices.csv"


def test_weights_are_equal_and_sum_to_one() -> None:
    weights = PORTFOLIO.weights

    assert len(weights) == 16
    assert np.isclose(weights.sum(), 1.0)
    assert np.allclose(weights, 1 / 16)


def test_price_file_has_every_ticker_and_no_gaps() -> None:
    # The service's only data contract: a date index and one column per ticker.
    prices = pd.read_csv(PRICES, index_col="date", parse_dates=True)

    assert list(prices.columns) == list(PORTFOLIO.tickers)
    assert prices.index.is_monotonic_increasing and not prices.index.has_duplicates
    assert prices.notna().all().all()
    assert (prices > 0).all().all()


def test_var_on_the_mock_prices_is_a_positive_loss_below_the_notional() -> None:
    # The same calculation /analytics reports as historical_var_99_1d.
    prices = pd.read_csv(PRICES, index_col="date", parse_dates=True)
    returns = prices.pct_change().dropna()

    var_99 = historical_var(portfolio_returns(returns, PORTFOLIO.weights), 0.99, PORTFOLIO.notional)

    assert 0 < var_99 < PORTFOLIO.notional
