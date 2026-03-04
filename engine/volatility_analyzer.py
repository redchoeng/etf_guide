import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VolatilityAnalyzer:
    """Volatility metrics for leveraged ETFs."""

    def __init__(self, config: dict = None):
        config = config or {}
        self.trading_days = config.get("trading_days_per_year", 252)

    def calculate_volatility(self, df: pd.DataFrame) -> dict:
        """Comprehensive volatility metrics."""
        close = df["Close"].dropna()
        if len(close) < 2:
            return {}

        daily_returns = close.pct_change().dropna()

        daily_vol = float(daily_returns.std())
        annualized_vol = daily_vol * np.sqrt(self.trading_days)

        # Monthly returns
        monthly = close.resample("ME").last().pct_change().dropna()
        monthly_vol = float(monthly.std()) if len(monthly) > 1 else 0

        # Rolling volatility
        rolling_vol_20 = daily_returns.rolling(20).std() * np.sqrt(self.trading_days)
        rolling_vol_60 = daily_returns.rolling(60).std() * np.sqrt(self.trading_days)

        # Sharpe ratio (assuming 0% risk-free rate)
        avg_daily = float(daily_returns.mean())
        sharpe = (avg_daily * self.trading_days) / annualized_vol if annualized_vol > 0 else 0

        return {
            "daily_vol": round(daily_vol * 100, 2),
            "monthly_vol": round(monthly_vol * 100, 2),
            "annualized_vol": round(annualized_vol * 100, 2),
            "daily_vol_20d": round(float(rolling_vol_20.iloc[-1]) * 100, 2) if len(rolling_vol_20.dropna()) > 0 else 0,
            "daily_vol_60d": round(float(rolling_vol_60.iloc[-1]) * 100, 2) if len(rolling_vol_60.dropna()) > 0 else 0,
            "max_daily_gain": round(float(daily_returns.max()) * 100, 2),
            "max_daily_loss": round(float(daily_returns.min()) * 100, 2),
            "pct_days_negative": round(float((daily_returns < 0).mean()) * 100, 2),
            "avg_daily_return": round(avg_daily * 100, 4),
            "sharpe_ratio": round(sharpe, 2),
            "rolling_vol_series": rolling_vol_60 * 100,
        }

    def calculate_var(self, df: pd.DataFrame, confidence: float = 0.95) -> dict:
        """Value at Risk calculation."""
        close = df["Close"].dropna()
        if len(close) < 30:
            return {}

        daily_returns = close.pct_change().dropna()

        var_95 = float(np.percentile(daily_returns, (1 - 0.95) * 100))
        var_99 = float(np.percentile(daily_returns, (1 - 0.99) * 100))

        # Monthly VaR
        monthly_returns = close.resample("ME").last().pct_change().dropna()
        monthly_var_95 = float(np.percentile(monthly_returns, 5)) if len(monthly_returns) > 5 else 0

        return {
            "daily_var_95": round(var_95 * 100, 2),
            "daily_var_99": round(var_99 * 100, 2),
            "monthly_var_95": round(monthly_var_95 * 100, 2),
        }
