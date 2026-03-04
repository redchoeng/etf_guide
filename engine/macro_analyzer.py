"""매크로 환경 분석기.

VIX(공포지수), 금리(US 10Y), 시장 추세를 분석하여
현재 시장 환경(상승장/하락장/횡보장)을 판단합니다.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class MacroAnalyzer:
    """VIX, 금리, 시장 추세 기반 매크로 환경 분석."""

    def __init__(self):
        self._cache = {}

    def analyze(self) -> dict:
        """매크로 환경 종합 분석.

        Returns:
            Dict with vix, rates, market_regime, macro_score, etc.
        """
        vix = self._get_vix()
        rate_10y = self._get_treasury_10y()
        sp500 = self._get_market_trend("SPY")

        # 시장 환경 판단
        regime = self._determine_regime(vix, sp500)
        macro_score = self._calculate_macro_score(vix, rate_10y, sp500, regime)

        return {
            "vix": vix,
            "vix_level": self._vix_level(vix),
            "rate_10y": rate_10y,
            "rate_level": self._rate_level(rate_10y),
            "sp500_trend": sp500,
            "regime": regime,
            "regime_kr": self._regime_kr(regime),
            "macro_score": macro_score,
            "description": self._regime_description(regime, vix, rate_10y),
        }

    def _get_vix(self) -> float:
        """VIX 현재값."""
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if hist.empty:
                return 20.0  # 기본값
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"VIX 조회 실패: {e}")
            return 20.0

    def _get_treasury_10y(self) -> float:
        """미국 10년 국채 금리."""
        try:
            tnx = yf.Ticker("^TNX")
            hist = tnx.history(period="5d")
            if hist.empty:
                return 4.0
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"10Y 금리 조회 실패: {e}")
            return 4.0

    def _get_market_trend(self, ticker: str = "SPY") -> dict:
        """시장(SPY) 추세 분석."""
        try:
            spy = yf.Ticker(ticker)
            hist = spy.history(period="1y")
            if hist.empty or len(hist) < 200:
                return {"trend": "UNKNOWN", "change_1m": 0, "change_3m": 0, "above_sma200": False}

            close = hist["Close"]
            current = float(close.iloc[-1])

            sma50 = float(close.rolling(50).mean().iloc[-1])
            sma200 = float(close.rolling(200).mean().iloc[-1])

            # 1개월, 3개월 수익률
            change_1m = (current / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
            change_3m = (current / float(close.iloc[-66]) - 1) * 100 if len(close) >= 66 else 0

            # 추세 판단
            if current > sma200 and sma50 > sma200:
                trend = "BULL"
            elif current < sma200 and sma50 < sma200:
                trend = "BEAR"
            elif current > sma200 and sma50 < sma200:
                trend = "RECOVERING"
            else:
                trend = "WEAKENING"

            return {
                "trend": trend,
                "price": current,
                "sma50": sma50,
                "sma200": sma200,
                "change_1m": change_1m,
                "change_3m": change_3m,
                "above_sma200": current > sma200,
            }
        except Exception as e:
            logger.warning(f"시장 추세 조회 실패: {e}")
            return {"trend": "UNKNOWN", "change_1m": 0, "change_3m": 0, "above_sma200": False}

    def _determine_regime(self, vix: float, sp500: dict) -> str:
        """시장 환경 판단.

        Returns:
            BULL_STRONG: 강한 상승장 (VIX 낮고 추세 상승)
            BULL: 상승장
            SIDEWAYS: 횡보장
            CORRECTION: 조정장
            BEAR: 하락장
            CRISIS: 위기 (VIX 극단적)
        """
        trend = sp500.get("trend", "UNKNOWN")
        change_1m = sp500.get("change_1m", 0)

        if vix >= 35:
            return "CRISIS"
        elif vix >= 25 and trend == "BEAR":
            return "BEAR"
        elif trend == "BEAR":
            return "CORRECTION"
        elif trend == "BULL" and vix < 15 and change_1m > 2:
            return "BULL_STRONG"
        elif trend == "BULL":
            return "BULL"
        elif trend == "RECOVERING":
            return "BULL"  # 회복 중도 상승장 취급
        else:
            return "SIDEWAYS"

    def _calculate_macro_score(self, vix: float, rate: float, sp500: dict, regime: str) -> float:
        """매크로 점수 (0~1). 높을수록 매수 유리한 환경.

        상승장에서도 적절한 점수를 주되, 위기/하락장에서 더 높은 점수 부여.
        """
        score = 0.0

        # VIX 기반 (0.0 ~ 0.35)
        if vix >= 35:
            score += 0.35  # 극단적 공포 = 최고의 매수 기회
        elif vix >= 25:
            score += 0.30
        elif vix >= 20:
            score += 0.20
        elif vix >= 15:
            score += 0.15  # 평균적
        else:
            score += 0.10  # 낮은 VIX = 안정적이지만 매수 급할 필요 없음

        # 금리 기반 (0.0 ~ 0.25)
        if rate <= 3.0:
            score += 0.25  # 저금리 = 주식 유리
        elif rate <= 4.0:
            score += 0.20
        elif rate <= 4.5:
            score += 0.15
        elif rate <= 5.0:
            score += 0.10
        else:
            score += 0.05  # 고금리 = 주식 불리

        # 시장 추세 기반 (0.0 ~ 0.40)
        trend = sp500.get("trend", "UNKNOWN")
        change_1m = sp500.get("change_1m", 0)

        if regime == "CRISIS":
            score += 0.40  # 위기 = 역발상 매수
        elif regime == "BEAR":
            score += 0.35
        elif regime == "CORRECTION":
            score += 0.30
        elif regime == "SIDEWAYS":
            score += 0.20
        elif regime == "BULL":
            # 상승장: 풀백(조정) 시 점수 높임
            if change_1m < -3:
                score += 0.30  # 상승장 내 단기 조정 = 좋은 매수 타이밍
            elif change_1m < 0:
                score += 0.25  # 약간의 풀백
            else:
                score += 0.18  # 순항 중 = 모멘텀 매수 가능
        elif regime == "BULL_STRONG":
            if change_1m < -2:
                score += 0.28  # 강한 상승장에서 조정 = 매수 기회
            else:
                score += 0.15  # 과열 주의

        return min(score, 1.0)

    def _vix_level(self, vix: float) -> str:
        if vix >= 35:
            return "EXTREME_FEAR"
        elif vix >= 25:
            return "FEAR"
        elif vix >= 20:
            return "CAUTIOUS"
        elif vix >= 15:
            return "NORMAL"
        else:
            return "COMPLACENT"

    def _rate_level(self, rate: float) -> str:
        if rate >= 5.0:
            return "HIGH"
        elif rate >= 4.0:
            return "ELEVATED"
        elif rate >= 3.0:
            return "MODERATE"
        else:
            return "LOW"

    def _regime_kr(self, regime: str) -> str:
        return {
            "BULL_STRONG": "강한 상승장",
            "BULL": "상승장",
            "SIDEWAYS": "횡보장",
            "CORRECTION": "조정장",
            "BEAR": "하락장",
            "CRISIS": "위기",
        }.get(regime, "알 수 없음")

    def _regime_description(self, regime: str, vix: float, rate: float) -> str:
        base = {
            "BULL_STRONG": "시장이 강하게 상승 중입니다. 소량 모멘텀 매수 또는 풀백 대기가 유리합니다.",
            "BULL": "상승 추세입니다. 단기 조정 시 분할매수를 시작하기 좋은 환경입니다.",
            "SIDEWAYS": "방향성이 불확실합니다. 그리드 매수를 천천히 진행하세요.",
            "CORRECTION": "조정 국면입니다. 그리드 레벨에 맞춰 적극적으로 매수하세요.",
            "BEAR": "하락장입니다. 예비금을 충분히 남기고 하위 레벨 위주로 매수하세요.",
            "CRISIS": "극단적 공포 구간입니다. 역사적으로 최고의 매수 기회이지만, 예비금 50% 이상 유지하세요.",
        }.get(regime, "")

        if vix >= 30:
            base += f" (VIX {vix:.0f} - 공포 극심)"
        if rate >= 5.0:
            base += f" (금리 {rate:.1f}% - 고금리 부담)"

        return base
