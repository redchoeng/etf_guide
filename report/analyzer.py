"""ETF 단일 종목 분석 + 판정 로직."""

import numpy as np

from engine.formatters import fmt_price
from engine.scorer import calculate_score
from engine.grid_calculator import GridCalculator

REGIME_ALLOCATION = {
    "BULL_STRONG": 0.75,
    "BULL":        0.70,
    "SIDEWAYS":    0.55,
    "CORRECTION":  0.50,
    "BEAR":        0.45,
    "CRISIS":      0.40,
}
STOP_LOSS_PCT = -50.0


def get_verdict(score, signal, drawdown_pct, rsi, next_buy, price,
                macro, mom_1m, trend_aligned):
    """사용자용 판정 + 상세 설명 (상승장 대응 포함)."""
    regime = macro.get("regime", "SIDEWAYS")
    regime_kr = macro.get("regime_kr", "")

    if score >= 75:
        verdict = "적극 매수 추천"
        if regime in ("BEAR", "CRISIS"):
            detail = f"[{regime_kr}] ATH 대비 {drawdown_pct:.0f}% 하락. 역사적 저점 영역입니다. 그리드 매수를 적극 실행하되 예비금을 꼭 남기세요."
        elif regime in ("BULL", "BULL_STRONG"):
            detail = f"[{regime_kr}] 상승 추세에서 매수 적기입니다. 소량씩 분할매수하세요."
        else:
            detail = "복합 시그널이 강한 매수를 가리킵니다. 분할매수 실행을 추천합니다."
    elif score >= 60:
        verdict = "매수 고려"
        if regime in ("BULL", "BULL_STRONG") and mom_1m < 0:
            detail = f"[{regime_kr}] 상승장에서 {mom_1m:.1f}% 풀백 중. SMA 지지 확인 후 매수 적기."
        elif regime in ("BULL", "BULL_STRONG"):
            detail = f"[{regime_kr}] 추세 양호. 소량 분할매수 또는 다음 풀백 대기."
        elif next_buy:
            gap = (next_buy.target_price - price) / price * 100
            detail = f"[{regime_kr}] 다음 그리드 레벨({fmt_price(next_buy.target_price)})까지 {abs(gap):.1f}% 남았습니다."
        else:
            detail = f"[{regime_kr}] 시그널 양호. 소량 분할매수를 시작해볼 만합니다."
    elif score >= 40:
        verdict = "관망"
        if regime in ("BULL_STRONG",) and drawdown_pct > -5:
            detail = f"[{regime_kr}] 고점 근처. 3~5% 풀백 시 진입하세요. 조급할 필요 없습니다."
        elif rsi > 65:
            detail = f"[{regime_kr}] RSI {rsi:.0f} 과매수 접근. 추가 매수보다 대기가 유리합니다."
        else:
            detail = f"[{regime_kr}] 뚜렷한 시그널 없음. 가격 변동 관찰 후 진입하세요."
    else:
        verdict = "대기"
        if regime in ("BULL_STRONG",) and drawdown_pct > -3:
            detail = f"[{regime_kr}] ATH 근처 과열 상태. 조정을 기다려 더 좋은 가격에 진입하세요."
        elif rsi > 70:
            detail = f"[{regime_kr}] RSI {rsi:.0f} 과매수. 단기 조정 가능성 높음. 기다리세요."
        else:
            detail = f"[{regime_kr}] 매수 조건 미충족. 조정을 기다리세요."

    return verdict, detail


def analyze_etf(ticker: str, preset: dict, config: dict, macro: dict) -> dict | None:
    """단일 ETF 종합 분석 (매크로 환경 포함)."""
    try:
        from engine.data_fetcher import ETFDataFetcher
        from engine.signal_generator import SignalGenerator

        fetcher = ETFDataFetcher(config.get("data", {}))
        signal_gen = SignalGenerator(config.get("signals", {}))

        df = fetcher.fetch_history(ticker, period="max")
        if df is None or df.empty or len(df) < 60:
            return None

        close = df["Close"]
        current_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])
        change_pct = (current_price - prev_price) / prev_price * 100

        signals = signal_gen.generate_signals(df)
        overall = signals.get("overall_signal", "HOLD")
        strength = signals.get("signal_strength", 0)
        rsi = signals.get("rsi_14", 50)

        high = close.cummax()
        drawdown_pct = float(((close.iloc[-1] - high.iloc[-1]) / high.iloc[-1]) * 100)
        ath = float(high.max())

        returns = close.pct_change().dropna()
        vol_annual = float(returns.std() * np.sqrt(252) * 100)

        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else sma50

        mom_1m = (current_price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
        mom_3m = (current_price / float(close.iloc[-66]) - 1) * 100 if len(close) >= 66 else 0
        trend_aligned = sma20 > sma50 > sma200 if len(close) >= 200 else sma20 > sma50

        score = calculate_score(
            rsi, drawdown_pct, current_price, sma20, sma50, sma200,
            vol_annual, strength, macro, mom_1m, trend_aligned,
        )

        regime = macro.get("regime", "SIDEWAYS")
        allocation = REGIME_ALLOCATION.get(regime, 0.55)
        budget = preset.get("suggested_budget", 10000)
        grid_budget = budget * allocation

        gc = GridCalculator(config.get("grid", {}))
        grid = gc.calculate_grid(
            reference_price=current_price,
            total_budget=grid_budget,
            num_levels=preset.get("suggested_levels", 10),
            spacing_pct=preset.get("suggested_spacing", 5.0),
            weighting="equal",
        )
        next_buy = next((gl for gl in grid if gl.target_price < current_price), None)
        upside_grid = gc.calculate_upside_grid(
            reference_price=current_price,
            total_budget=grid_budget,
            num_levels=5,
            spacing_pct=3.0,
        )

        recent_52w = close.tail(252)
        high_52w = float(recent_52w.max())
        low_52w = float(recent_52w.min())
        pos_52w = (current_price - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50

        stop_loss_price = current_price * (1 + STOP_LOSS_PCT / 100)

        verdict, verdict_detail = get_verdict(
            score, overall, drawdown_pct, rsi, next_buy, current_price,
            macro, mom_1m, trend_aligned,
        )

        weekly_base = preset.get("weekly_base", 0)
        from engine.scorer import dd_multiplier as _dd_mult
        weekly_mult = _dd_mult(drawdown_pct)
        weekly_buy = round(weekly_base * weekly_mult) if weekly_base else 0

        return {
            "ticker": ticker,
            "name": preset.get("name", ticker),
            "underlying": preset.get("underlying", ""),
            "leverage": preset.get("leverage", 2),
            "category": preset.get("category", ""),
            "currency": preset.get("currency", "USD"),
            "display": preset.get("display", ticker),
            "price": current_price,
            "change_pct": change_pct,
            "signal": overall,
            "strength": strength,
            "score": score,
            "rsi": rsi,
            "drawdown_pct": drawdown_pct,
            "ath": ath,
            "vol_annual": vol_annual,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "mom_1m": mom_1m,
            "mom_3m": mom_3m,
            "trend_aligned": trend_aligned,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pos_52w": pos_52w,
            "grid_levels": grid,
            "upside_grid": upside_grid,
            "next_buy": next_buy,
            "total_budget": budget,
            "grid_budget": grid_budget,
            "reserve_budget": budget * (1 - allocation),
            "stop_loss_price": stop_loss_price,
            "verdict": verdict,
            "verdict_detail": verdict_detail,
            "allocation": allocation,
            "num_levels": preset.get("suggested_levels", 10),
            "spacing_pct": preset.get("suggested_spacing", 5.0),
            "weekly_base": weekly_base,
            "weekly_buy": weekly_buy,
            "weekly_mult": weekly_mult,
        }
    except Exception as e:
        print(f"  {ticker} 분석 실패: {e}")
        return None
