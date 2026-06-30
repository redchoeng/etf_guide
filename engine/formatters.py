def fmt_price(price: float, currency: str = "USD") -> str:
    """통화별 가격 표기 ($xx.xx / ₩x,xxx). 이전 money() / fmt_price() 통합."""
    if currency == "KRW":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def buy_phrase(mult: float) -> str:
    """낙폭 배수를 친근한 문구로."""
    if mult >= 5: return "5배로 풀매수 찬스! 🔥"
    if mult >= 4: return "4배로 팍팍 담아! 💥"
    if mult >= 3: return "3배로 더 사! 🔴"
    if mult >= 2: return "2배로 더 담아! 🟠"
    if mult >= 1.5: return "평소보다 1.5배 더! 🟡"
    return "평소대로 적립 🟢"


def verdict_color(score):
    if score >= 75: return "#2E7D32", "#E8F5E9", "#4CAF50"
    elif score >= 60: return "#1565C0", "#E3F2FD", "#2196F3"
    elif score >= 40: return "#E65100", "#FFF3E0", "#FF9800"
    else: return "#C62828", "#FFEBEE", "#F44336"


def regime_color(regime):
    return {
        "BULL_STRONG": ("#1B5E20", "#E8F5E9", "🚀"),
        "BULL":        ("#2E7D32", "#E8F5E9", "📈"),
        "SIDEWAYS":    ("#E65100", "#FFF3E0", "➡️"),
        "CORRECTION":  ("#BF360C", "#FBE9E7", "📉"),
        "BEAR":        ("#B71C1C", "#FFEBEE", "🐻"),
        "CRISIS":      ("#4A148C", "#F3E5F5", "🔥"),
    }.get(regime, ("#5D4E37", "#FFF8DC", "❓"))


def signal_emoji(score_or_signal):
    if isinstance(score_or_signal, (int, float)):
        if score_or_signal >= 75: return "🟢"
        elif score_or_signal >= 60: return "🔵"
        elif score_or_signal >= 40: return "🟡"
        else: return "🟠"
    return {"STRONG_BUY": "🟢", "BUY": "🔵", "HOLD": "🟡", "WAIT": "🟠"}.get(score_or_signal, "⚪")
