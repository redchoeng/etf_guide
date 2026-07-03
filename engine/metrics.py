"""가격 시계열 공통 지표 계산.

alerts/checker.py(텔레그램 알림)와 report/analyzer.py(HTML 리포트)가
같은 숫자를 보도록 단일 소스로 유지한다.
"""

import numpy as np


def compute_metrics(df) -> dict | None:
    """OHLCV DataFrame → 공통 지표 dict. 데이터 부족 시 None."""
    if df is None or df.empty or len(df) < 60:
        return None

    close = df["Close"]
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    change_pct = (price - prev) / prev * 100

    high = close.cummax()
    ath = float(high.iloc[-1])
    drawdown_pct = (price - ath) / ath * 100

    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else sma50

    mom_1m = (price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
    mom_3m = (price / float(close.iloc[-66]) - 1) * 100 if len(close) >= 66 else 0
    trend_aligned = sma20 > sma50 > sma200 if len(close) >= 200 else sma20 > sma50

    vol_annual = float(close.pct_change().dropna().std() * np.sqrt(252) * 100)

    recent_52w = close.tail(252)
    high_52w = float(recent_52w.max())
    low_52w = float(recent_52w.min())
    pos_52w = (price - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50

    return {
        "price": price,
        "change_pct": change_pct,
        "ath": ath,
        "drawdown_pct": drawdown_pct,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "mom_1m": mom_1m,
        "mom_3m": mom_3m,
        "trend_aligned": trend_aligned,
        "vol_annual": vol_annual,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pos_52w": pos_52w,
    }
