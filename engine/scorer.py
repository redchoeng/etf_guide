# 낙폭 구간: (임계값, 구간명, 매수배수)
# 1배 나스닥 ETF 기준 — -7%는 연 2~3회 오는 풀백, -12%는 조정장,
# -20%는 약세장, -30% 이하는 위기 수준 (레버리지용 -50% 구간은 1배에선 비현실적)
DD_ZONES = [
    (-3,  "-3%",  1.0),
    (-7,  "-7%",  1.5),
    (-12, "-12%", 2.0),
    (-20, "-20%", 3.0),
    (-30, "-30%", 4.0),
    (-40, "-40%", 5.0),
]


def dd_multiplier(drawdown_pct: float) -> float:
    """현재 낙폭(%, 음수)에 해당하는 매수 배수."""
    mult = 1.0
    for threshold, _, m in DD_ZONES:
        if drawdown_pct <= threshold:
            mult = m
    return mult


def calculate_score(rsi, drawdown_pct, price, sma20, sma50, sma200,
                    vol, strength, macro, mom_1m, trend_aligned):
    """매수 매력도 점수 (100점 만점).

    가격위치(20) + RSI(10) + SMA/추세(10) + 변동성(10) + 매크로(20) + 시그널(15) + 모멘텀(15)
    """
    score = 0
    regime = macro.get("regime", "SIDEWAYS")
    dd = abs(drawdown_pct)

    # === 가격 위치 (20점) ===
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

    # === RSI (10점) ===
    if rsi < 25: score += 10
    elif rsi < 30: score += 9
    elif rsi < 40: score += 7
    elif rsi < 50: score += 5
    elif rsi < 55: score += 4
    elif rsi < 65: score += 2
    elif rsi < 70: score += 1

    # === SMA/추세 (10점) ===
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

    # === 변동성 (10점) ===
    if vol <= 25: score += 10
    elif vol <= 35: score += 8
    elif vol <= 45: score += 5
    elif vol <= 55: score += 3
    else: score += 1

    # === 매크로 (20점) ===
    macro_score = macro.get("macro_score", 0.5)
    score += int(macro_score * 20)

    # === 복합 시그널 (15점) ===
    score += int(strength * 15)

    # === 모멘텀 보너스 (15점) ===
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
