"""Telegram 알림 모듈.

DB 없이 프리셋(etf_presets.yaml) 기반으로 동작합니다.
매크로 환경 + 개선된 점수 체계로 알림 조건을 판단합니다.

알림 조건:
  1. 매수 점수 60점 이상 (매크로+모멘텀 반영)
  2. 그리드 레벨 도달 (프리셋 기반 자동 계산)
  3. 급락 알림 (1일 -5% 이상 하락)
  4. 매시간 요약 (전체 ETF 현황)
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

# 중복 알림 방지 캐시: key -> timestamp
_alert_cache: dict[str, float] = {}
ALERT_COOLDOWN = 3600  # 1시간


def _should_alert(key: str) -> bool:
    """쿨다운 내 중복 알림 방지."""
    now = time.time()
    last = _alert_cache.get(key, 0)
    if now - last < ALERT_COOLDOWN:
        return False
    _alert_cache[key] = now
    return True


class TelegramNotifier:
    """Telegram Bot API를 통한 알림 발송."""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """메시지 전송."""
        if not self.is_configured:
            logger.warning("Telegram 봇 토큰/채팅 ID가 설정되지 않았습니다")
            return False

        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram 전송 실패: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram 전송 오류: {e}")
            return False

    def send_grid_alert(self, ticker: str, level: int, target_price: float,
                        current_price: float, quantity: int, budget: float) -> bool:
        """그리드 레벨 도달 알림."""
        if not _should_alert(f"grid_{ticker}_{level}"):
            return False

        msg = (
            f"📊 <b>그리드 매수 시그널</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"레벨: L{level}\n"
            f"목표가: ${target_price:.2f}\n"
            f"현재가: ${current_price:.2f}\n"
            f"매수 수량: {quantity}주\n"
            f"매수 금액: ${budget:,.0f}\n\n"
            f"⚠️ 그리드 레벨에 도달했습니다!"
        )
        return self.send_message(msg)

    def send_score_alert(self, ticker: str, score: int, verdict: str,
                         price: float, rsi: float, drawdown: float,
                         regime_kr: str, mom_1m: float) -> bool:
        """매수 점수 알림 (60점 이상)."""
        if not _should_alert(f"score_{ticker}_{score // 10}"):
            return False

        emoji = "🟢" if score >= 75 else "🔵"

        msg = (
            f"{emoji} <b>매수 추천 알림</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"점수: <b>{score}점</b> ({verdict})\n"
            f"현재가: ${price:.2f}\n"
            f"RSI: {rsi:.0f}\n"
            f"ATH 낙폭: {drawdown:.1f}%\n"
            f"1개월: {mom_1m:+.1f}%\n"
            f"시장: {regime_kr}\n"
        )
        return self.send_message(msg)

    def send_crash_alert(self, ticker: str, price: float,
                         change_pct: float, drawdown: float) -> bool:
        """급락 알림."""
        if not _should_alert(f"crash_{ticker}"):
            return False

        msg = (
            f"🔴 <b>급락 알림</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"현재가: ${price:.2f} ({change_pct:+.1f}%)\n"
            f"ATH 대비: {drawdown:.1f}%\n\n"
            f"📉 그리드 매수 기회일 수 있습니다!"
        )
        return self.send_message(msg)

    def send_summary(self, summaries: list[dict], macro: dict) -> bool:
        """종합 요약 알림."""
        if not _should_alert("summary"):
            return False

        regime_kr = macro.get("regime_kr", "")
        vix = macro.get("vix", 0)
        rate = macro.get("rate_10y", 0)

        lines = [
            f"📋 <b>ETF 현황 요약</b>\n",
            f"시장: {regime_kr} | VIX {vix:.1f} | 금리 {rate:.1f}%\n",
        ]

        for s in summaries:
            emoji = "🟢" if s["score"] >= 75 else ("🔵" if s["score"] >= 60 else ("🟡" if s["score"] >= 40 else "🟠"))
            lines.append(
                f"{emoji} <b>{s['ticker']}</b> {s['score']}점: "
                f"${s['price']:.2f} ({s['change']:+.1f}%) "
                f"RSI {s['rsi']:.0f}"
            )

        buy_count = len([s for s in summaries if s["score"] >= 60])
        if buy_count > 0:
            lines.append(f"\n🔔 매수 추천: {buy_count}개 종목")

        return self.send_message("\n".join(lines))


def check_and_notify(config: dict):
    """프리셋 기반 자동 알림 (DB 불필요).

    1. 프리셋에서 모든 ETF 로드
    2. 매크로 환경 분석
    3. 각 ETF 점수 계산 + 그리드 레벨 체크
    4. 조건 충족 시 텔레그램 알림
    """
    import numpy as np
    from engine.data_fetcher import ETFDataFetcher
    from engine.signal_generator import SignalGenerator
    from engine.grid_calculator import GridCalculator
    from engine.macro_analyzer import MacroAnalyzer

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.info("Telegram 미설정, 알림 스킵")
        return

    # 프리셋 로드
    preset_path = Path(__file__).parent.parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        presets = yaml.safe_load(f)

    # 매크로 분석
    logger.info("매크로 환경 분석 중...")
    macro_analyzer = MacroAnalyzer()
    macro = macro_analyzer.analyze()
    regime = macro.get("regime", "SIDEWAYS")
    regime_kr = macro.get("regime_kr", "")
    macro_score = macro.get("macro_score", 0.5)
    logger.info(f"  시장: {regime_kr} | VIX: {macro['vix']:.1f} | 매크로: {macro_score:.0%}")

    fetcher = ETFDataFetcher(config.get("data", {}))
    signal_gen = SignalGenerator(config.get("signals", {}))
    gc = GridCalculator(config.get("grid", {}))

    summaries = []
    alerts_sent = 0

    for ticker, preset in presets.get("presets", {}).items():
        try:
            df = fetcher.fetch_history(ticker, period="1y")
            if df is None or df.empty or len(df) < 60:
                logger.warning(f"{ticker}: 데이터 부족, 스킵")
                continue

            close = df["Close"]
            current_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            change_pct = (current_price - prev_price) / prev_price * 100

            # 시그널
            signals = signal_gen.generate_signals(df)
            strength = signals.get("signal_strength", 0)
            rsi = signals.get("rsi_14", 50)

            # 낙폭
            high = close.cummax()
            drawdown_pct = float(((current_price - high.iloc[-1]) / high.iloc[-1]) * 100)

            # SMA
            sma20 = float(close.rolling(20).mean().iloc[-1])
            sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
            sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else sma50

            # 모멘텀
            mom_1m = (current_price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
            trend_aligned = sma20 > sma50 > sma200 if len(close) >= 200 else sma20 > sma50

            # 변동성
            vol = float(close.pct_change().dropna().std() * np.sqrt(252) * 100)

            # 점수 계산 (generate_report.py와 동일한 로직)
            score = _calculate_score(
                rsi, drawdown_pct, current_price, sma20, sma50, sma200,
                vol, strength, macro, mom_1m, trend_aligned,
            )

            # 판정
            verdict = (
                "적극 매수" if score >= 75 else
                "매수 고려" if score >= 60 else
                "관망" if score >= 40 else "대기"
            )

            logger.info(f"  {ticker}: ${current_price:.2f} ({change_pct:+.1f}%) | {score}점 {verdict}")

            # === 알림 조건 ===

            # 1) 매수 점수 60점 이상
            if score >= 60:
                sent = notifier.send_score_alert(
                    ticker, score, verdict, current_price,
                    rsi, drawdown_pct, regime_kr, mom_1m,
                )
                if sent:
                    alerts_sent += 1
                    logger.info(f"    🔔 매수 추천 알림 발송 ({score}점)")

            # 2) 그리드 레벨 도달 체크
            budget = preset.get("suggested_budget", 10000) * 0.5  # 예비금 50%
            grid = gc.calculate_grid(
                reference_price=current_price * 1.05,  # 현재가 +5%에서 그리드 시작
                total_budget=budget,
                num_levels=preset.get("suggested_levels", 10),
                spacing_pct=preset.get("suggested_spacing", 5.0),
                weighting="linear",
            )

            for gl in grid:
                if current_price <= gl.target_price:
                    sent = notifier.send_grid_alert(
                        ticker, gl.level_number, gl.target_price,
                        current_price, gl.quantity, gl.budget_allocation,
                    )
                    if sent:
                        alerts_sent += 1
                        logger.info(f"    🔔 그리드 L{gl.level_number} 도달 알림")
                    break  # 가장 가까운 레벨만

            # 3) 급락 알림 (1일 -5% 이상)
            if change_pct <= -5:
                sent = notifier.send_crash_alert(
                    ticker, current_price, change_pct, drawdown_pct,
                )
                if sent:
                    alerts_sent += 1
                    logger.info(f"    🔔 급락 알림 ({change_pct:.1f}%)")

            summaries.append({
                "ticker": ticker,
                "price": current_price,
                "change": change_pct,
                "rsi": rsi,
                "score": score,
                "drawdown": drawdown_pct,
            })

        except Exception as e:
            logger.error(f"  {ticker} 체크 실패: {e}")

    # 4) 요약 알림
    if summaries:
        notifier.send_summary(summaries, macro)

    logger.info(f"체크 완료: {len(summaries)}종목, {alerts_sent}건 알림")


def _calculate_score(rsi, drawdown_pct, price, sma20, sma50, sma200,
                     vol, strength, macro, mom_1m, trend_aligned):
    """매수 매력도 점수 (generate_report.py와 동일)."""
    score = 0
    regime = macro.get("regime", "SIDEWAYS")

    dd = abs(drawdown_pct)
    if regime in ("BEAR", "CRISIS", "CORRECTION"):
        if dd >= 40: score += 20
        elif dd >= 30: score += 17
        elif dd >= 20: score += 14
        elif dd >= 10: score += 10
        elif dd >= 5: score += 6
        else: score += 2
    else:
        if dd >= 15: score += 18
        elif dd >= 10: score += 15
        elif dd >= 5: score += 10
        elif mom_1m < -5: score += 14
        elif mom_1m < -2: score += 10
        elif mom_1m < 0: score += 7
        else: score += 4

    if rsi < 25: score += 10
    elif rsi < 30: score += 9
    elif rsi < 40: score += 7
    elif rsi < 50: score += 5
    elif rsi < 55: score += 4
    elif rsi < 65: score += 2
    elif rsi < 70: score += 1

    if regime in ("BEAR", "CRISIS"):
        if price < sma200: score += 10
        elif price < sma50: score += 7
        elif price < sma20: score += 4
        else: score += 1
    else:
        if trend_aligned and price > sma20: score += 9
        elif trend_aligned and price > sma50: score += 8
        elif price > sma200: score += 6
        elif price > sma50: score += 4
        else: score += 2

    if vol <= 25: score += 10
    elif vol <= 35: score += 8
    elif vol <= 45: score += 5
    elif vol <= 55: score += 3
    else: score += 1

    macro_score = macro.get("macro_score", 0.5)
    score += int(macro_score * 20)

    score += int(strength * 15)

    if regime in ("BULL", "BULL_STRONG"):
        if trend_aligned: score += 6
        if mom_1m > 5: score += 3
        elif mom_1m > 0: score += 5
        elif mom_1m > -3: score += 7
        else: score += 4
        if 0 < mom_1m < 8: score += 2
    elif regime in ("CORRECTION", "BEAR", "CRISIS"):
        if mom_1m > 3: score += 8
        elif mom_1m > 0: score += 5
        elif dd >= 30: score += 7
        else: score += 3
    else:
        if mom_1m < -3: score += 8
        elif abs(mom_1m) < 2: score += 5
        else: score += 3

    return min(score, 100)
