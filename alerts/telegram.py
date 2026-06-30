import logging
import os

import requests

from alerts.state import _should_alert
from engine.formatters import fmt_price, buy_phrase
from engine.scorer import dd_multiplier

logger = logging.getLogger(__name__)

REPORT_URL = os.environ.get("REPORT_URL", "https://redchoeng.github.io/etf_guide/")


def report_kb(label: str = "📊 자세히 보기") -> dict:
    """웹 리포트로 가는 인라인 URL 버튼."""
    return {"inline_keyboard": [[{"text": label, "url": REPORT_URL}]]}


class TelegramNotifier:
    """Telegram Bot API를 통한 알림 발송."""

    def __init__(self, bot_token: str = None, chat_id: str = None, state: dict = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._state = state if state is not None else {}

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML",
                     reply_markup: dict = None) -> bool:
        if not self.is_configured:
            logger.warning("Telegram 봇 토큰/채팅 ID가 설정되지 않았습니다")
            return False
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Telegram 전송 실패: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram 전송 오류: {e}")
            return False

    def send_drawdown_batch(self, dd_alerts: list) -> bool:
        """'지금 더 사라' 통합 알림 (모아서 1건)."""
        if not dd_alerts:
            return False
        lines = ["🛒 <b>지금 더 사라!</b>\n"]
        for a in dd_alerts:
            name = a.get("display", a["ticker"])
            cur = a.get("currency", "USD")
            mult = a["mult"]
            weekly_base = a.get("weekly_base", 0)
            dd = a["drawdown"]
            if weekly_base:
                amt = round(weekly_base * mult)
                lines.append(f"<b>{name}</b> → {fmt_price(amt, cur)} 사라 (ATH {dd:.0f}%, {mult:.1f}배)")
            else:
                lines.append(f"<b>{name}</b> → {mult:.1f}배 매수 (ATH {dd:.0f}%)")
        return self.send_message("\n".join(lines), reply_markup=report_kb())

    def send_crash_alert(self, ticker: str, price: float, change_pct: float,
                         drawdown: float, currency: str = "USD", display: str = None) -> bool:
        """급락 알림."""
        if not _should_alert(f"crash_{ticker}", self._state):
            return False
        name = display or ticker
        mult = dd_multiplier(drawdown)
        msg = (
            f"🚨 <b>{name} 지금 많이 빠졌어!</b>\n"
            f"<i>하루 새 큰 하락 — 매수 찬스 알림</i>\n\n"
            f"현재가: {fmt_price(price, currency)} (오늘 {change_pct:+.1f}%)\n"
            f"전고점 대비: {drawdown:.0f}%\n\n"
            f"👉 {buy_phrase(mult)}"
        )
        return self.send_message(msg, reply_markup=report_kb())

    def send_summary(self, summaries: list, macro: dict) -> bool:
        """하루 1번 '이번 주 얼마 사라' 가이드."""
        if not _should_alert("summary", self._state):
            return False
        regime_kr = macro.get("regime_kr", "")
        vix = macro.get("vix", 0)
        lines = [
            "📅 <b>이번 주 뭐 얼마 사지?</b>",
            f"<i>시장: {regime_kr} · VIX {vix:.1f}</i>\n",
        ]
        for s in summaries:
            name = s.get("display", s["ticker"])
            cur = s.get("currency", "USD")
            mult = s.get("mult", dd_multiplier(s.get("drawdown", 0)))
            weekly_buy = s.get("weekly_buy", 0)
            dd = s.get("drawdown", 0)

            if weekly_buy:
                amt_str = fmt_price(weekly_buy, cur)
                if mult > 1.0:
                    lines.append(f"<b>{name}</b> → {amt_str} 사라 (ATH {dd:.0f}%, {mult:.1f}배)")
                else:
                    lines.append(f"<b>{name}</b> → {amt_str} 사라 (기본 DCA)")
            else:
                # weekly_base 미설정 시 배수만 표시
                lines.append(f"<b>{name}</b> → {'x'+str(mult) if mult > 1.0 else '기본'} (ATH {dd:.0f}%)")

        lines.append("\n<i>presets.yaml의 weekly_base × 낙폭배수 자동 계산</i>")
        return self.send_message("\n".join(lines), reply_markup=report_kb())

    # ── 하위 호환 (직접 호출 시 유지) ──

    def send_score_alert(self, ticker: str, score: int, verdict: str,
                         price: float, rsi: float, drawdown: float,
                         regime_kr: str, mom_1m: float,
                         currency: str = "USD", display: str = None) -> bool:
        if not _should_alert(f"score_{ticker}_{score // 10}", self._state):
            return False
        name = display or ticker
        emoji = "🟢" if score >= 75 else "🔵"
        mult = dd_multiplier(drawdown)
        mult_line = f"매수 배수: <b>x{mult:.1f}</b>\n" if mult > 1.0 else ""
        msg = (
            f"{emoji} <b>매수 추천 알림</b>\n\n"
            f"종목: <b>{name}</b>\n"
            f"점수: <b>{score}점</b> ({verdict})\n"
            f"현재가: {fmt_price(price, currency)}\n"
            f"RSI: {rsi:.0f}\n"
            f"ATH 낙폭: {drawdown:.1f}%\n"
            f"{mult_line}"
            f"1개월: {mom_1m:+.1f}%\n"
            f"시장: {regime_kr}\n"
        )
        return self.send_message(msg)
