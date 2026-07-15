"""네이버 실시간 시세 (한국 상장 종목).

yfinance 일봉은 장 시작 직후 당일 캔들이 없어서 전일 종가가 나온다.
아침 알림이 당일 시초가를 반영하도록 네이버 현재가로 덮어쓴다.
"""

import logging

import requests

logger = logging.getLogger(__name__)

BASIC_URL = "https://m.stock.naver.com/api/stock/{code}/basic"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def get_quote(code: str):
    """실시간 현재가/등락률. 실패 시 None (호출부는 yfinance 값 유지)."""
    try:
        d = requests.get(BASIC_URL.format(code=code), headers=HEADERS, timeout=10).json()
        price = _num(d.get("closePrice"))
        if price is None or price <= 0:
            return None
        ratio = _num(d.get("fluctuationsRatio"))
        return {
            "price": price,
            "change_pct": ratio if ratio is not None else 0.0,
            "market_status": d.get("marketStatus", ""),
            "traded_at": d.get("localTradedAt", ""),
        }
    except Exception as e:
        logger.debug(f"실시간 시세 실패 {code}: {e}")
        return None
