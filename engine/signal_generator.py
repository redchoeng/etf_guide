import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Technical signal generation for buy/sell timing."""

    def __init__(self, config: dict = None):
        config = config or {}
        self.rsi_period = config.get("rsi_period", 14)
        self.sma_short = config.get("sma_short", 20)
        self.sma_long = config.get("sma_long", 50)
        self.sma_trend = config.get("sma_trend", 200)
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.rsi_overbought = config.get("rsi_overbought", 70)

    def generate_signals(self, df: pd.DataFrame,
                         grid_levels: list = None) -> dict:
        """Generate current trading signals.

        Args:
            df: DataFrame with 'Close' column.
            grid_levels: Optional list of GridLevel objects for grid proximity.

        Returns:
            Dict with RSI, SMA, drawdown, grid signals and composite score.
        """
        close = df["Close"].dropna()
        if len(close) < self.sma_trend:
            return self._minimal_signals(close, grid_levels)

        current_price = float(close.iloc[-1])

        # RSI
        rsi_series = self.calculate_rsi(close, self.rsi_period)
        rsi_val = float(rsi_series.iloc[-1])

        if rsi_val < self.rsi_oversold:
            rsi_signal = "OVERSOLD"
        elif rsi_val > self.rsi_overbought:
            rsi_signal = "OVERBOUGHT"
        else:
            rsi_signal = "NEUTRAL"

        # SMA
        sma20 = float(self.calculate_sma(close, self.sma_short).iloc[-1])
        sma50 = float(self.calculate_sma(close, self.sma_long).iloc[-1])
        sma200 = float(self.calculate_sma(close, self.sma_trend).iloc[-1])

        if sma20 > sma50 and current_price > sma200:
            sma_signal = "UPTREND"
        elif sma20 < sma50 and current_price < sma200:
            sma_signal = "DOWNTREND"
        elif sma20 > sma50:
            sma_signal = "RECOVERING"
        else:
            sma_signal = "WEAKENING"

        # Golden/Death cross
        sma20_prev = float(self.calculate_sma(close, self.sma_short).iloc[-2])
        sma50_prev = float(self.calculate_sma(close, self.sma_long).iloc[-2])
        if sma20_prev < sma50_prev and sma20 > sma50:
            cross_signal = "GOLDEN_CROSS"
        elif sma20_prev > sma50_prev and sma20 < sma50:
            cross_signal = "DEATH_CROSS"
        else:
            cross_signal = "NONE"

        price_vs_sma200 = "ABOVE" if current_price > sma200 else "BELOW"

        # ATH & drawdown
        ath = float(close.cummax().max())
        distance_from_ath = (current_price - ath) / ath * 100
        current_dd = distance_from_ath

        # Grid proximity
        current_grid_level = None
        next_grid_target = None
        grid_score = 0.5

        if grid_levels:
            for gl in grid_levels:
                target = gl.target_price if hasattr(gl, "target_price") else gl.get("target_price", 0)
                level_num = gl.level_number if hasattr(gl, "level_number") else gl.get("level_number", 0)
                if current_price <= target:
                    current_grid_level = level_num
                    grid_score = 1.0
                    break
                else:
                    next_grid_target = target
                    distance = (current_price - target) / current_price
                    if distance < 0.02:
                        grid_score = 0.8
                    else:
                        grid_score = max(0, 1.0 - distance * 10)
                    current_grid_level = level_num - 1

        # Composite signal
        rsi_score = self._rsi_to_score(rsi_val)
        sma_score = self._sma_to_score(current_price, sma20, sma50, sma200)
        dd_score = min(1.0, abs(current_dd) / 50.0)

        composite = rsi_score * 0.30 + sma_score * 0.25 + dd_score * 0.30 + grid_score * 0.15

        if composite >= 0.80:
            overall = "STRONG_BUY"
        elif composite >= 0.60:
            overall = "BUY"
        elif composite >= 0.40:
            overall = "HOLD"
        else:
            overall = "WAIT"

        reasons = self._build_reasons(rsi_val, rsi_signal, sma_signal,
                                       cross_signal, current_dd, grid_score)

        return {
            "current_price": round(current_price, 2),
            "rsi_14": round(rsi_val, 2),
            "rsi_signal": rsi_signal,
            "sma_20": round(sma20, 2),
            "sma_50": round(sma50, 2),
            "sma_200": round(sma200, 2),
            "sma_signal": sma_signal,
            "sma_cross_signal": cross_signal,
            "price_vs_sma200": price_vs_sma200,
            "ath_price": round(ath, 2),
            "distance_from_ath_pct": round(distance_from_ath, 2),
            "current_drawdown_pct": round(current_dd, 2),
            "current_grid_level": current_grid_level,
            "next_grid_target": round(next_grid_target, 2) if next_grid_target else None,
            "overall_signal": overall,
            "signal_strength": round(composite, 3),
            "component_scores": {
                "rsi": round(rsi_score, 3),
                "sma": round(sma_score, 3),
                "drawdown": round(dd_score, 3),
                "grid": round(grid_score, 3),
            },
            "reasons": reasons,
        }

    def _minimal_signals(self, close: pd.Series, grid_levels=None) -> dict:
        """Fallback when not enough data for full analysis."""
        current_price = float(close.iloc[-1]) if len(close) > 0 else 0
        ath = float(close.cummax().max()) if len(close) > 0 else 0
        dd = (current_price - ath) / ath * 100 if ath > 0 else 0

        result = {
            "current_price": round(current_price, 2),
            "ath_price": round(ath, 2),
            "distance_from_ath_pct": round(dd, 2),
            "current_drawdown_pct": round(dd, 2),
            "overall_signal": "HOLD",
            "signal_strength": 0.5,
            "reasons": ["Insufficient data for full analysis"],
        }

        if len(close) >= self.rsi_period + 1:
            rsi = float(self.calculate_rsi(close, self.rsi_period).iloc[-1])
            result["rsi_14"] = round(rsi, 2)

        return result

    def _rsi_to_score(self, rsi: float) -> float:
        if rsi < 30:
            return 1.0
        elif rsi < 40:
            return 0.7
        elif rsi < 60:
            return 0.5
        elif rsi < 70:
            return 0.3
        else:
            return 0.0

    def _sma_to_score(self, price: float, sma20: float, sma50: float,
                       sma200: float) -> float:
        if price < sma200 and sma20 < sma50:
            return 1.0  # Downtrend = best buy opportunity
        elif price < sma200 and sma20 > sma50:
            return 0.7  # Potential recovery
        elif price > sma200 and sma20 < sma50:
            return 0.5  # Weakening
        else:
            return 0.3  # Uptrend = less need to buy

    def _build_reasons(self, rsi, rsi_signal, sma_signal, cross_signal,
                        current_dd, grid_score) -> list[str]:
        reasons = []
        if rsi_signal == "OVERSOLD":
            reasons.append(f"RSI {rsi:.1f} - oversold territory (< 30)")
        elif rsi_signal == "OVERBOUGHT":
            reasons.append(f"RSI {rsi:.1f} - overbought territory (> 70)")

        if sma_signal == "DOWNTREND":
            reasons.append("Price below SMA200, SMA20 < SMA50 - downtrend")
        elif sma_signal == "RECOVERING":
            reasons.append("SMA20 crossed above SMA50 - potential recovery")
        elif sma_signal == "UPTREND":
            reasons.append("Price above SMA200 in uptrend")

        if cross_signal == "GOLDEN_CROSS":
            reasons.append("Golden Cross detected (SMA20 > SMA50)")
        elif cross_signal == "DEATH_CROSS":
            reasons.append("Death Cross detected (SMA20 < SMA50)")

        if current_dd < -30:
            reasons.append(f"Significant drawdown: {current_dd:.1f}% from ATH")
        elif current_dd < -10:
            reasons.append(f"Moderate drawdown: {current_dd:.1f}% from ATH")

        if grid_score >= 0.8:
            reasons.append("Price near or at grid buy level")

        return reasons

    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0).ewm(span=period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(span=period, adjust=False).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()
