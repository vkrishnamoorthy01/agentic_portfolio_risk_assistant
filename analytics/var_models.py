"""Historical Value-at-Risk and portfolio return aggregation.

Ported from risk_project/var_models.py in quant_risk_and_trading_portfolio.

Inputs are validated rather than silently coerced: a weight with no matching
return column (or a return column with no weight) would otherwise drop out
of the weighted sum, and pandas' default NaN skipping would turn a missing
return into a zero return. Both would yield a plausible-looking but wrong
number, so they raise InvalidInputError instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class InvalidInputError(ValueError):
    """Inputs to a risk calculation are incomplete or inconsistent."""


def portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Compute a weighted portfolio return series from individual asset returns.

    Args:
        returns: DataFrame of asset returns, one column per ticker.
        weights: Portfolio weights indexed by ticker, summing to 1.0.

    Returns:
        Series of portfolio returns aligned to `returns`' index.

    Raises:
        InvalidInputError: if tickers don't match, weights don't sum to 1,
            or any return or weight is missing or non-finite.
    """
    missing_returns = sorted(set(weights.index) - set(returns.columns))
    missing_weights = sorted(set(returns.columns) - set(weights.index))
    if missing_returns or missing_weights:
        raise InvalidInputError(
            f"Weights and returns cover different tickers: no returns for {missing_returns}, "
            f"no weights for {missing_weights}."
        )
    if not np.isfinite(weights.to_numpy(dtype=float)).all():
        raise InvalidInputError("Weights contain missing or non-finite values.")
    if not np.isclose(weights.sum(), 1.0):
        raise InvalidInputError(f"Weights sum to {weights.sum():.6f}, not 1.0.")
    if returns.empty:
        raise InvalidInputError("No returns to aggregate.")
    values = returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        bad = returns.columns[~np.isfinite(values).all(axis=0)].tolist()
        raise InvalidInputError(f"Missing or non-finite returns for {bad}.")

    aligned_weights = weights.reindex(returns.columns)
    return returns.mul(aligned_weights, axis=1).sum(axis=1)


def historical_var(returns: pd.Series, confidence_level: float, notional: float = 1.0) -> float:
    """Compute historical (empirical) VaR from a portfolio return series.

    Takes the empirical quantile of realized returns directly, so it makes no
    distributional assumption but is only as good as the historical sample.

    Args:
        returns: Portfolio return series.
        confidence_level: Confidence level, e.g. 0.95 or 0.99.
        notional: Portfolio notional value used to scale VaR into currency terms.

    Returns:
        VaR as a positive number representing potential loss.

    Raises:
        InvalidInputError: on an empty series, missing returns, or a
            confidence level outside (0, 1).
    """
    if not 0.0 < confidence_level < 1.0:
        raise InvalidInputError(f"confidence_level must be between 0 and 1, got {confidence_level}.")
    if returns.empty:
        raise InvalidInputError("No returns to compute VaR from.")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise InvalidInputError("Return series contains missing or non-finite values.")
    quantile = 1.0 - confidence_level
    var_return = returns.quantile(quantile)
    return -notional * var_return
