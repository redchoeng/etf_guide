"""check_and_notify: 프리셋 기반 자동 알림 (DB 불필요)."""

import logging
from pathlib import Path

import yaml

from alerts.state import _load_state, _save_state, _should_alert
from alerts.telegram import TelegramNotifier
from engine.metrics import compute_metrics
from engine.scorer import DD_ZONES, calculate_score, dd_multiplier

logger = logging.getLogger(__name__)


def check_and_notify(config: dict, mode: str = "digest"):
    """프리셋 기반 자동 알림.

    mode="digest": 주간 매수 가이드 + 긴급(급락/더사라) 알림
    mode="urgent": 긴급(급락/더사라) 알림만
    """
    from engine.data_fetcher import ETFDataFetcher
    from engine.signal_generator import SignalGenerator
    from engine.macro_analyzer import MacroAnalyzer

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.info("Telegram 미설정, 알림 스킵")
        return

    preset_path = Path(__file__).parent.parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        presets = yaml.safe_load(f)

    logger.info("매크로 환경 분석 중...")
    macro_analyzer = MacroAnalyzer()
    macro = macro_analyzer.analyze()
    regime_kr = macro.get("regime_kr", "")
    macro_score = macro.get("macro_score", 0.5)
    logger.info(f"  시장: {regime_kr} | VIX: {macro['vix']:.1f} | 매크로: {macro_score:.0%}")

    fetcher = ETFDataFetcher(config.get("data", {}))
    signal_gen = SignalGenerator(config.get("signals", {}))

    price_state = _load_state()
    notifier._state = price_state
    summaries = []
    dd_alerts = []
    alerts_sent = 0

    for ticker, preset in presets.get("presets", {}).items():
        try:
            currency = preset.get("currency", "USD")
            display = preset.get("display", ticker)
            weekly_base = preset.get("weekly_base", 0)

            # period="max": 진짜 전고점(ATH) 기준 낙폭
            df = fetcher.fetch_history(ticker, period="max")
            m = compute_metrics(df)
            if m is None:
                logger.warning(f"{ticker}: 데이터 부족, 스킵")
                continue

            signals = signal_gen.generate_signals(df)
            strength = signals.get("signal_strength", 0)
            rsi = signals.get("rsi_14", 50)

            score = calculate_score(
                rsi, m["drawdown_pct"], m["price"], m["sma20"], m["sma50"], m["sma200"],
                m["vol_annual"], strength, macro, m["mom_1m"], m["trend_aligned"],
            )
            verdict = (
                "적극 매수" if score >= 75 else
                "매수 고려" if score >= 60 else
                "관망" if score >= 40 else "대기"
            )
            logger.info(f"  {ticker}: {m['price']:.2f} ({m['change_pct']:+.1f}%) | {score}점 {verdict}")

            # '지금 더 사라' — x1.5(-7%)부터, 이전보다 깊어졌을 때만
            prev_dd = price_state.get(f"{ticker}_dd", 0)
            current_zone = None
            for threshold, zone_name, mult in DD_ZONES:
                if m["drawdown_pct"] <= threshold:
                    current_zone = (threshold, zone_name, mult)
            if current_zone and current_zone[2] > 1.0 and prev_dd > current_zone[0]:
                zone_key = f"dd_{ticker}_{current_zone[0]}"
                if _should_alert(zone_key, price_state):
                    dd_alerts.append({
                        "ticker": ticker,
                        "display": display,
                        "price": m["price"],
                        "drawdown": m["drawdown_pct"],
                        "ath": m["ath"],
                        "zone": current_zone[1],
                        "mult": current_zone[2],
                        "currency": currency,
                        "weekly_base": weekly_base,
                    })
                    logger.info(f"    📌 낙폭 {current_zone[1]} 구간 진입 감지")

            price_state[ticker] = m["price"]
            price_state[f"{ticker}_dd"] = m["drawdown_pct"]

            # 급락 알림 (1일 -3% 이상 — 1배 ETF 기준)
            if m["change_pct"] <= -3:
                sent = notifier.send_crash_alert(
                    ticker, m["price"], m["change_pct"], m["drawdown_pct"], currency, display,
                )
                if sent:
                    alerts_sent += 1
                    logger.info(f"    🔔 급락 알림 ({m['change_pct']:.1f}%)")

            mult = dd_multiplier(m["drawdown_pct"])
            weekly_buy = round(weekly_base * mult) if weekly_base else 0
            summaries.append({
                "ticker": ticker,
                "display": display,
                "price": m["price"],
                "change": m["change_pct"],
                "rsi": rsi,
                "score": score,
                "drawdown": m["drawdown_pct"],
                "currency": currency,
                "weekly_base": weekly_base,
                "weekly_buy": weekly_buy,
                "mult": mult,
            })

        except Exception as e:
            logger.error(f"  {ticker} 체크 실패: {e}")

    if dd_alerts:
        sent = notifier.send_drawdown_batch(dd_alerts)
        if sent:
            alerts_sent += 1
            logger.info(f"  🔔 낙폭 통합 알림 발송 ({len(dd_alerts)}종목)")

    if summaries and mode == "digest":
        notifier.send_summary(summaries, macro)

    _save_state(price_state)
    logger.info(f"체크 완료: {len(summaries)}종목, {alerts_sent}건 알림")
