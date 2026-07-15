"""추정 iNAV — 한국장 마감 중 미국 기초자산 가격으로 ETF 적정가 추정.

est = 한국 종가 x (1 + 기초 바스켓 미국장 수익률 + USD/KRW 변화율)

기초 바스켓 수익률은 보유 수량(스냅샷) x 미국 종가로 가중.
환노출형 ETF 가정 (두 ETF 모두 UH 아님). 현금/미매핑 종목만큼 오차 있음.
"""

import logging

import yfinance as yf

from alerts.holdings import _load_snapshot, _ticker_of, _fetch_us_prices
from alerts.state import _load_state, _save_state, _should_alert
from alerts.telegram import TelegramNotifier, report_kb
from engine.scorer import dd_multiplier

logger = logging.getLogger(__name__)


def _kr_close_and_ath(kr_ticker: str):
    px = yf.download(kr_ticker, period="max", auto_adjust=True, progress=False)["Close"]
    px = (px.iloc[:, 0] if hasattr(px, "columns") else px).dropna()
    if len(px) < 2:
        return None, None
    return float(px.iloc[-1]), float(px.cummax().iloc[-1])


def estimate_inav(kr_ticker: str, snapshot: dict, prices: dict,
                  kr_close: float = None, ath: float = None):
    """{est, kr_close, r_basket, r_fx, dd_est, mult_est} 또는 None.

    kr_close/ath를 넘기면 야후 재조회 없이 계산 (리포트 생성 시 재활용).
    """
    code = kr_ticker.split(".")[0]
    entry = snapshot.get(code) or {}
    holdings = entry.get("holdings") or {}
    if not holdings:
        return None

    total = 0.0
    weighted_ret = 0.0
    items = []  # (티커, 평가액, 전일등락%)
    up_cnt = down_cnt = 0
    for name, qty in holdings.items():
        tk = _ticker_of(name)
        if tk and tk in prices:
            last, day_pct, _ = prices[tk]
            v = qty * last
            total += v
            weighted_ret += v * (day_pct / 100)
            items.append((tk, v, day_pct))
            if day_pct > 0.05:
                up_cnt += 1
            elif day_pct < -0.05:
                down_cnt += 1
    if total <= 0:
        return None
    r_basket = weighted_ret / total
    coverage = len(items) / len(holdings) * 100

    if not kr_close:
        kr_close, ath = _kr_close_and_ath(kr_ticker)
    if not kr_close:
        return None
    if not ath:
        ath = kr_close

    r_fx = prices.get("KRW=X", (0, 0, 0))[1] / 100
    est = kr_close * (1 + r_basket + r_fx)
    ath_eff = max(ath, est)
    dd_est = (est / ath_eff - 1) * 100
    # 트리맵용: 비중(%) 내림차순
    items.sort(key=lambda x: -x[1])
    tm_items = [(tk, v / total * 100, chg) for tk, v, chg in items]
    return {
        "est": est,
        "kr_close": kr_close,
        "r_basket": r_basket * 100,
        "r_fx": r_fx * 100,
        "dd_est": dd_est,
        "mult_est": dd_multiplier(dd_est),
        "up_cnt": up_cnt,
        "down_cnt": down_cnt,
        "coverage": coverage,
        "items": tm_items,
    }


def send_inav_alert(config: dict) -> bool:
    """미국장 마감 후 추정 iNAV 알림 (하루 1건)."""
    from pathlib import Path
    import yaml

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.info("Telegram 미설정, iNAV 알림 스킵")
        return False

    state = _load_state()
    notifier._state = state
    if not _should_alert("inav", state):
        logger.info("iNAV 알림 이미 발송됨 (오늘)")
        return False

    preset_path = Path(__file__).parent.parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        presets = yaml.safe_load(f).get("presets", {})

    snapshot = _load_snapshot()

    # 두 ETF의 매핑 티커 + 환율을 한 번에 조회
    tickers = set()
    for ticker in presets:
        entry = snapshot.get(ticker.split(".")[0]) or {}
        for name in (entry.get("holdings") or {}):
            tk = _ticker_of(name)
            if tk:
                tickers.add(tk)
    tickers.add("KRW=X")
    prices = _fetch_us_prices(sorted(tickers))
    if not prices:
        logger.warning("iNAV: 미국 시세 조회 실패")
        return False

    lines = ["🌙 <b>미국장 마감 — 오늘 아침 예상가</b>"]
    ok = 0
    for ticker, preset in presets.items():
        display = preset.get("display", ticker)
        r = estimate_inav(ticker, snapshot, prices)
        if not r:
            continue
        ok += 1
        chg = (r["est"] / r["kr_close"] - 1) * 100
        emoji = "🔺" if chg > 0.1 else ("🔻" if chg < -0.1 else "▪")
        action = f"{r['mult_est']:.1f}배 구간" if r["mult_est"] > 1.0 else "기본 매수 구간"
        lines.append(
            f"<b>{display}</b> ₩{r['est']:,.0f} {emoji}{chg:+.1f}% 예상"
            f" · ATH {r['dd_est']:.0f}% → {action}"
        )
        lines.append(
            f"  <i>바스켓 {r['r_basket']:+.1f}% · 환율 {r['r_fx']:+.1f}%"
            f" · ▲{r['up_cnt']} ▼{r['down_cnt']} · 반영률 {r['coverage']:.0f}%</i>"
        )
    if ok == 0:
        return False
    lines.append("<i>추정치 — 현금/괴리율 미반영, 시초가와 다를 수 있음</i>")

    sent = notifier.send_message("\n".join(lines), reply_markup=report_kb())
    if sent:
        logger.info(f"🌙 추정 iNAV 알림 발송 ({ok}종목)")
    _save_state(state)
    return sent
