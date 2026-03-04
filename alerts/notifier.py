"""Telegram 알림 모듈."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


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
                        current_price: float, quantity: int) -> bool:
        """그리드 레벨 도달 알림."""
        msg = (
            f"📊 <b>그리드 매수 시그널</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"레벨: {level}\n"
            f"목표가: ${target_price:.2f}\n"
            f"현재가: ${current_price:.2f}\n"
            f"매수 수량: {quantity}주\n"
            f"매수 금액: ${target_price * quantity:,.2f}\n\n"
            f"⚠️ 매수 타이밍에 도달했습니다!"
        )
        return self.send_message(msg)

    def send_signal_alert(self, ticker: str, signal: str, strength: float,
                          price: float, rsi: float, reasons: list[str]) -> bool:
        """매수 시그널 알림."""
        signal_kr = {
            "STRONG_BUY": "🟢 적극 매수",
            "BUY": "🔵 매수",
            "HOLD": "🟡 보유",
            "WAIT": "🟠 대기",
        }
        signal_text = signal_kr.get(signal, signal)

        reasons_text = "\n".join(f"  • {r}" for r in reasons) if reasons else "  없음"

        msg = (
            f"📈 <b>매수 시그널 알림</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"판정: {signal_text} (강도: {strength:.0%})\n"
            f"현재가: ${price:.2f}\n"
            f"RSI: {rsi:.1f}\n\n"
            f"근거:\n{reasons_text}"
        )
        return self.send_message(msg)

    def send_profit_target_alert(self, ticker: str, avg_cost: float,
                                 current_price: float, pnl_pct: float,
                                 total_shares: int) -> bool:
        """목표 수익률 도달 알림."""
        total_value = current_price * total_shares
        total_cost = avg_cost * total_shares
        profit = total_value - total_cost

        msg = (
            f"🎯 <b>목표 수익률 도달!</b>\n\n"
            f"종목: <b>{ticker}</b>\n"
            f"평균 단가: ${avg_cost:.2f}\n"
            f"현재가: ${current_price:.2f}\n"
            f"수익률: {pnl_pct:+.2f}%\n"
            f"보유 수량: {total_shares}주\n"
            f"평가 손익: ${profit:+,.2f}\n\n"
            f"💰 매도를 고려하세요!"
        )
        return self.send_message(msg)

    def send_daily_summary(self, summaries: list[dict]) -> bool:
        """일일 종합 요약 알림."""
        lines = ["📋 <b>일일 ETF 현황 요약</b>\n"]

        for s in summaries:
            signal_emoji = {"STRONG_BUY": "🟢", "BUY": "🔵", "HOLD": "🟡", "WAIT": "🟠"}.get(s.get("signal", ""), "⚪")
            lines.append(
                f"{signal_emoji} <b>{s['ticker']}</b>: "
                f"${s['price']:.2f} (ATH대비 {s['drawdown']:.1f}%) "
                f"RSI {s['rsi']:.0f}"
            )

        return self.send_message("\n".join(lines))


def check_and_notify(config: dict):
    """그리드 레벨 도달 및 시그널 체크 후 알림 발송.

    scheduler나 cron에서 호출하도록 설계.
    """
    from engine.data_fetcher import ETFDataFetcher
    from engine.signal_generator import SignalGenerator
    from storage.db import Database

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.info("Telegram 미설정, 알림 스킵")
        return

    db = Database()
    fetcher = ETFDataFetcher(config.get("data", {}))
    signal_gen = SignalGenerator(config.get("signals", {}))

    etf_configs = db.get_all_etf_configs()
    summaries = []

    for cfg in etf_configs:
        ticker = cfg["ticker"]
        current_price = fetcher.get_current_price(ticker)
        if not current_price:
            continue

        # 그리드 레벨 체크
        grid_levels = db.get_grid_levels(ticker)
        for gl in grid_levels:
            if not gl.get("is_filled") and current_price <= gl["target_price"]:
                notifier.send_grid_alert(
                    ticker, gl["level_number"], gl["target_price"],
                    current_price, gl["target_quantity"],
                )

        # 시그널 체크
        df = fetcher.fetch_history(ticker, period="1y")
        if df is not None and not df.empty:
            signals = signal_gen.generate_signals(df, grid_levels)
            overall = signals.get("overall_signal", "HOLD")

            if overall in ("STRONG_BUY", "BUY"):
                notifier.send_signal_alert(
                    ticker, overall,
                    signals.get("signal_strength", 0),
                    signals.get("current_price", 0),
                    signals.get("rsi_14", 0),
                    signals.get("reasons", []),
                )

            # 수익률 목표 체크
            purchases = db.get_purchases(ticker)
            if purchases:
                total_shares = sum(p["quantity"] for p in purchases)
                total_cost = sum(p["total_cost"] for p in purchases)
                if total_shares > 0:
                    avg_cost = total_cost / total_shares
                    pnl_pct = (current_price - avg_cost) / avg_cost * 100
                    profit_target = cfg.get("profit_target_pct", 10.0)

                    if pnl_pct >= profit_target:
                        notifier.send_profit_target_alert(
                            ticker, avg_cost, current_price, pnl_pct, total_shares,
                        )

            summaries.append({
                "ticker": ticker,
                "price": current_price,
                "drawdown": signals.get("current_drawdown_pct", 0),
                "rsi": signals.get("rsi_14", 0),
                "signal": overall,
            })

    if summaries:
        notifier.send_daily_summary(summaries)
