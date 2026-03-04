"""숫자 및 통화 포맷터."""


def fmt_currency(value: float, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"${value:,.{decimals}f}"


def fmt_pct(value: float, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}%"


def fmt_pct_plain(value: float, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{decimals}f}%"


def fmt_number(value: float, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return f"{value:,.{decimals}f}"


def signal_color(signal: str) -> str:
    colors = {
        "STRONG_BUY": "#00c853",
        "BUY": "#2196f3",
        "HOLD": "#ffc107",
        "WAIT": "#ff9800",
        "SELL": "#f44336",
        "OVERSOLD": "#00c853",
        "NEUTRAL": "#ffc107",
        "OVERBOUGHT": "#f44336",
        "UPTREND": "#00c853",
        "RECOVERING": "#2196f3",
        "WEAKENING": "#ff9800",
        "DOWNTREND": "#f44336",
    }
    return colors.get(signal, "#9e9e9e")


def signal_emoji(signal: str) -> str:
    emojis = {
        "STRONG_BUY": "🟢",
        "BUY": "🔵",
        "HOLD": "🟡",
        "WAIT": "🟠",
        "SELL": "🔴",
    }
    return emojis.get(signal, "⚪")


def signal_kr(signal: str) -> str:
    """시그널을 한국어로 변환."""
    kr_map = {
        "STRONG_BUY": "적극 매수",
        "BUY": "매수",
        "HOLD": "보유",
        "WAIT": "대기",
        "SELL": "매도",
        "OVERSOLD": "과매도",
        "NEUTRAL": "중립",
        "OVERBOUGHT": "과매수",
        "UPTREND": "상승추세",
        "RECOVERING": "회복중",
        "WEAKENING": "약화중",
        "DOWNTREND": "하락추세",
    }
    return kr_map.get(signal, signal)
