import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DrawdownEvent:
    """Single drawdown event with full metadata."""
    start_date: datetime
    trough_date: datetime
    recovery_date: Optional[datetime]
    peak_price: float
    trough_price: float
    drawdown_pct: float
    duration_to_trough_days: int
    recovery_days: Optional[int]
    total_duration_days: Optional[int]
    label: str = ""


class DrawdownAnalyzer:
    """Historical drawdown analysis for leveraged ETFs."""

    KNOWN_CRASHES = [
        {"start": "2020-02-01", "end": "2020-05-01", "label": "COVID-19 Crash"},
        {"start": "2022-01-01", "end": "2022-12-31", "label": "2022 Bear Market"},
        {"start": "2018-09-01", "end": "2019-01-01", "label": "Q4 2018 Selloff"},
        {"start": "2008-09-01", "end": "2009-06-01", "label": "GFC 2008-09"},
        {"start": "2015-08-01", "end": "2016-03-01", "label": "2015-16 Correction"},
    ]

    def __init__(self, config: dict = None):
        config = config or {}
        self.min_drawdown_pct = config.get("min_drawdown_pct", 10.0)

    def analyze(self, df: pd.DataFrame, ticker: str = "") -> dict:
        """Comprehensive drawdown analysis.

        Args:
            df: DataFrame with 'Close' column and DatetimeIndex.
            ticker: ETF ticker for labeling.

        Returns:
            Dict with max_drawdown, events, current_drawdown, etc.
        """
        close = df["Close"].dropna()
        if close.empty:
            return {"max_drawdown": 0, "drawdown_events": [], "current_drawdown": 0}

        cummax = close.cummax()
        drawdown_series = (close - cummax) / cummax * 100

        max_dd = float(drawdown_series.min())
        current_dd = float(drawdown_series.iloc[-1])
        ath_price = float(cummax.max())
        ath_idx = cummax.idxmax()

        events = self._detect_events(close, drawdown_series)

        return {
            "ticker": ticker,
            "max_drawdown": round(max_dd, 2),
            "avg_drawdown": round(np.mean([e.drawdown_pct for e in events]), 2) if events else 0,
            "median_drawdown": round(float(np.median([e.drawdown_pct for e in events])), 2) if events else 0,
            "num_events": len(events),
            "drawdown_events": events,
            "current_drawdown": round(current_dd, 2),
            "ath_price": round(ath_price, 2),
            "ath_date": ath_idx,
            "drawdown_series": drawdown_series,
            "current_price": round(float(close.iloc[-1]), 2),
        }

    def _detect_events(self, close: pd.Series, dd_series: pd.Series) -> list[DrawdownEvent]:
        """Detect discrete drawdown events."""
        events = []
        in_drawdown = False
        peak_idx = None
        peak_price = 0.0

        i = 0
        indices = close.index.tolist()
        n = len(indices)

        while i < n:
            dd_val = dd_series.iloc[i]

            if not in_drawdown:
                if dd_val <= -self.min_drawdown_pct:
                    in_drawdown = True
                    # Find the peak that preceded this drawdown
                    j = i - 1
                    while j >= 0 and dd_series.iloc[j] < 0:
                        j -= 1
                    peak_idx = max(0, j)
                    peak_price = float(close.iloc[peak_idx])
                i += 1
                continue

            # We're in a drawdown, find the end (recovery to peak)
            if close.iloc[i] >= peak_price:
                # Recovered - find the trough
                trough_idx = dd_series.iloc[peak_idx:i + 1].idxmin()
                trough_date = trough_idx
                trough_price = float(close.loc[trough_idx])
                trough_dd = float(dd_series.loc[trough_idx])

                peak_date = indices[peak_idx]
                recovery_date = indices[i]

                dur_to_trough = (trough_date - peak_date).days
                recovery_days = (recovery_date - trough_date).days
                total_days = (recovery_date - peak_date).days

                label = self._label_event(peak_date, trough_date)

                events.append(DrawdownEvent(
                    start_date=peak_date,
                    trough_date=trough_date,
                    recovery_date=recovery_date,
                    peak_price=round(peak_price, 2),
                    trough_price=round(trough_price, 2),
                    drawdown_pct=round(trough_dd, 2),
                    duration_to_trough_days=dur_to_trough,
                    recovery_days=recovery_days,
                    total_duration_days=total_days,
                    label=label,
                ))

                in_drawdown = False
            i += 1

        # Handle ongoing drawdown (not yet recovered)
        if in_drawdown and peak_idx is not None:
            trough_idx = dd_series.iloc[peak_idx:].idxmin()
            trough_price = float(close.loc[trough_idx])
            trough_dd = float(dd_series.loc[trough_idx])
            peak_date = indices[peak_idx]
            dur_to_trough = (trough_idx - peak_date).days
            label = self._label_event(peak_date, trough_idx)

            events.append(DrawdownEvent(
                start_date=peak_date,
                trough_date=trough_idx,
                recovery_date=None,
                peak_price=round(peak_price, 2),
                trough_price=round(trough_price, 2),
                drawdown_pct=round(trough_dd, 2),
                duration_to_trough_days=dur_to_trough,
                recovery_days=None,
                total_duration_days=None,
                label=label,
            ))

        return events

    def _label_event(self, start_date, trough_date) -> str:
        for crash in self.KNOWN_CRASHES:
            cs = pd.Timestamp(crash["start"])
            ce = pd.Timestamp(crash["end"])
            if cs <= pd.Timestamp(trough_date) <= ce:
                return crash["label"]
        return ""

    def compare_leveraged_vs_underlying(
        self,
        leveraged_df: pd.DataFrame,
        underlying_df: pd.DataFrame,
        leverage_factor: int = 2,
    ) -> dict:
        """Compare actual leveraged ETF drawdowns vs theoretical."""
        lev_close = leveraged_df["Close"].dropna()
        und_close = underlying_df["Close"].dropna()

        # Align dates
        common_idx = lev_close.index.intersection(und_close.index)
        lev_close = lev_close.loc[common_idx]
        und_close = und_close.loc[common_idx]

        lev_cummax = lev_close.cummax()
        und_cummax = und_close.cummax()

        lev_dd = ((lev_close - lev_cummax) / lev_cummax * 100).min()
        und_dd = ((und_close - und_cummax) / und_cummax * 100).min()
        theoretical_dd = und_dd * leverage_factor

        # Overall returns
        lev_return = (lev_close.iloc[-1] / lev_close.iloc[0] - 1) * 100
        und_return = (und_close.iloc[-1] / und_close.iloc[0] - 1) * 100
        expected_return = und_return * leverage_factor
        decay = lev_return - expected_return

        return {
            "leveraged_max_dd": round(float(lev_dd), 2),
            "underlying_max_dd": round(float(und_dd), 2),
            "theoretical_max_dd": round(float(theoretical_dd), 2),
            "decay_impact_dd": round(float(lev_dd - theoretical_dd), 2),
            "leveraged_total_return": round(float(lev_return), 2),
            "underlying_total_return": round(float(und_return), 2),
            "expected_leveraged_return": round(float(expected_return), 2),
            "leverage_decay": round(float(decay), 2),
            "period_start": str(common_idx[0].date()),
            "period_end": str(common_idx[-1].date()),
        }

    def recovery_time_analysis(self, df: pd.DataFrame) -> list[dict]:
        """For each drawdown threshold, calculate recovery statistics."""
        close = df["Close"].dropna()
        cummax = close.cummax()
        dd_series = (close - cummax) / cummax * 100

        thresholds = [10, 20, 30, 40, 50, 60, 70, 80]
        results = []

        for threshold in thresholds:
            events_at_threshold = []
            in_dd = False
            peak_price = 0.0
            dd_start = None

            for i in range(len(close)):
                if not in_dd:
                    if dd_series.iloc[i] <= -threshold:
                        in_dd = True
                        j = i - 1
                        while j >= 0 and dd_series.iloc[j] < 0:
                            j -= 1
                        peak_price = float(close.iloc[max(0, j)])
                        dd_start = close.index[max(0, j)]
                else:
                    if close.iloc[i] >= peak_price:
                        recovery_date = close.index[i]
                        days = (recovery_date - dd_start).days
                        events_at_threshold.append(days)
                        in_dd = False

            if events_at_threshold:
                results.append({
                    "threshold_pct": threshold,
                    "occurrences": len(events_at_threshold),
                    "avg_recovery_days": round(np.mean(events_at_threshold)),
                    "median_recovery_days": round(float(np.median(events_at_threshold))),
                    "worst_recovery_days": max(events_at_threshold),
                    "best_recovery_days": min(events_at_threshold),
                })
            else:
                results.append({
                    "threshold_pct": threshold,
                    "occurrences": 0,
                    "avg_recovery_days": None,
                    "median_recovery_days": None,
                    "worst_recovery_days": None,
                    "best_recovery_days": None,
                })

        return results

    def calculate_leverage_decay(
        self,
        leveraged_df: pd.DataFrame,
        underlying_df: pd.DataFrame,
        leverage_factor: int = 2,
        window_days: int = 252,
    ) -> pd.DataFrame:
        """Rolling leverage decay calculation."""
        lev_close = leveraged_df["Close"].dropna()
        und_close = underlying_df["Close"].dropna()

        common_idx = lev_close.index.intersection(und_close.index)
        lev_close = lev_close.loc[common_idx]
        und_close = und_close.loc[common_idx]

        if len(common_idx) < window_days:
            return pd.DataFrame()

        und_return = und_close.pct_change(window_days) * 100
        expected_return = und_return * leverage_factor
        actual_return = lev_close.pct_change(window_days) * 100
        decay = actual_return - expected_return

        result = pd.DataFrame({
            "underlying_return": und_return,
            "expected_return": expected_return,
            "actual_return": actual_return,
            "decay_pct": decay,
        }, index=common_idx).dropna()

        return result
