"""Unit tests for analytics/var_models.py.

The functions here are a copy of risk_project/var_models.py in
quant_risk_and_trading_portfolio, so these tests are copied from that repo's
tests/test_var_models.py: the same behavior is pinned down in both places
until the two copies are merged into one shared package.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from var_models import InvalidInputError, historical_var, portfolio_returns


def test_portfolio_returns_matches_manual_weighted_sum() -> None:
    returns = pd.DataFrame({"A": [0.01, -0.02, 0.03], "B": [-0.01, 0.02, 0.00]})
    weights = pd.Series({"A": 0.4, "B": 0.6})

    result = portfolio_returns(returns, weights)

    expected = 0.4 * returns["A"] + 0.6 * returns["B"]
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_historical_var_matches_empirical_quantile() -> None:
    returns = pd.Series(np.linspace(-0.10, 0.10, 101))  # includes exact 5th/1st percentiles

    result = historical_var(returns, confidence_level=0.95, notional=1_000.0)

    expected = -1_000.0 * returns.quantile(0.05)
    assert np.isclose(result, expected)
    assert result > 0  # a loss, reported as a positive number


def test_historical_var_scales_linearly_with_notional() -> None:
    returns = pd.Series(np.linspace(-0.10, 0.10, 101))

    var_1x = historical_var(returns, confidence_level=0.99, notional=1_000.0)
    var_10x = historical_var(returns, confidence_level=0.99, notional=10_000.0)

    assert np.isclose(var_10x, 10 * var_1x)


# --- input validation: bad inputs raise instead of producing a plausible number ---

_RETURNS = pd.DataFrame({"A": [0.01, -0.02, 0.03], "B": [-0.01, 0.02, 0.00]})


def test_a_weight_with_no_returns_column_is_rejected() -> None:
    # Before validation, C would have silently dropped out of the weighted sum.
    with pytest.raises(InvalidInputError, match="no returns for \\['C'\\]"):
        portfolio_returns(_RETURNS, pd.Series({"A": 0.4, "B": 0.4, "C": 0.2}))


def test_a_returns_column_with_no_weight_is_rejected() -> None:
    with pytest.raises(InvalidInputError, match="no weights for \\['B'\\]"):
        portfolio_returns(_RETURNS, pd.Series({"A": 1.0}))


def test_weights_that_do_not_sum_to_one_are_rejected() -> None:
    with pytest.raises(InvalidInputError, match="sum to"):
        portfolio_returns(_RETURNS, pd.Series({"A": 0.4, "B": 0.4}))


def test_a_missing_return_is_rejected_not_treated_as_zero() -> None:
    returns = _RETURNS.copy()
    returns.iloc[1, 0] = np.nan  # would otherwise count as a 0% day for A

    with pytest.raises(InvalidInputError, match="\\['A'\\]"):
        portfolio_returns(returns, pd.Series({"A": 0.4, "B": 0.6}))


def test_historical_var_rejects_empty_or_missing_returns_and_bad_confidence() -> None:
    with pytest.raises(InvalidInputError):
        historical_var(pd.Series([], dtype=float), 0.99)
    with pytest.raises(InvalidInputError):
        historical_var(pd.Series([0.01, np.nan]), 0.99)
    with pytest.raises(InvalidInputError):
        historical_var(pd.Series([0.01, -0.02]), 1.5)
