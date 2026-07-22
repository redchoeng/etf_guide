"""운용사 공식 사이트에서 전체 구성종목 직접 조회 (메인 소스).

2025-12-27 KRX가 비공식 클라이언트(pykrx 등)를 차단하기 시작하면서
KRX 경로가 거의 항상 실패한다. 대신 두 운용사가 홈페이지에서 직접
전종목 데이터를 로그인 없이 공개하고 있어 이쪽을 메인으로 쓴다.

  - TIMEFOLIO(426030): 엑셀 다운로드 (pdf_excel.php) — 종목코드/명/수량/비중
  - KoACT(0015B0):     JSON API (etf-pdf.do)         — 종목명/수량/비중/티커

두 소스 다 블룸버그 스타일 티커("NVDA US EQUITY")를 함께 주므로
engine.formatters 쪽 이름→티커 매핑 테이블 없이도 바로 티커를 뽑는다.
"""

import io
import logging
import re
import warnings
from datetime import datetime, timezone, timedelta

import requests
import urllib3

logger = logging.getLogger(__name__)

# timeetf.co.kr 인증서 체인 문제로 verify=False 사용 — 관련 경고만 숨긴다.
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

_NON_STOCK_KEYWORDS = ("현금", "설정", "INDEX", "E-MINI", "FUTURE")


def _is_stock(name: str) -> bool:
    up = name.upper()
    return not any(kw in up or kw in name for kw in _NON_STOCK_KEYWORDS)


def _ticker_from_code(code: str):
    """'NVDA US EQUITY' / 'AMD US Equity' -> 'NVDA'."""
    if not code:
        return None
    m = re.match(r"([A-Za-z.]+)\s+(US|KS)\b", code.strip())
    return m.group(1).upper() if m else None


def fetch_timefolio_full(idx: str = "2"):
    """타임폴리오 전종목 (엑셀 다운로드).

    반환: (기준일 or None, {종목명: 수량}, {종목명: 티커})
    실패 시 (None, {}, {}).
    """
    import openpyxl

    url = f"https://timeetf.co.kr/pdf_excel.php?idx={idx}&"
    referer = f"https://timeetf.co.kr/m11_view.php?idx={idx}"
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": referer},
                         timeout=20, verify=False)
        r.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        ws = wb.active
        holdings, tickers = {}, {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 5:
                continue
            code, name, qty = row[0], row[1], row[2]
            if not name or qty in (None, ""):
                continue
            name = str(name).strip()
            try:
                q = float(qty)
            except (TypeError, ValueError):
                continue
            if q > 0 and _is_stock(name):
                holdings[name] = q
                tk = _ticker_from_code(str(code) if code else "")
                if tk:
                    tickers[name] = tk
        if not holdings:
            return None, {}, {}
        trd_dt = datetime.now(KST).strftime("%Y-%m-%d")
        return trd_dt, holdings, tickers
    except Exception as e:
        logger.info(f"타임폴리오 공식 전종목 조회 실패: {e}")
        return None, {}, {}


def fetch_samsung_full(fid: str = "2ETFQ1"):
    """KoACT(삼성액티브) 전종목 (JSON API).

    반환: (기준일 or None, {종목명: 수량}, {종목명: 티커})
    실패 시 (None, {}, {}).
    """
    today = datetime.now(KST).strftime("%Y%m%d")
    url = f"https://www.samsungactive.co.kr/api/v1/product/etf-pdf/{fid}.do"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20,
                         params={"gijunYMD": today})
        r.raise_for_status()
        data = r.json()
        pdf = data.get("pdf") or {}
        rows = pdf.get("list") or []
        if not rows:
            return None, {}, {}
        holdings, tickers = {}, {}
        for row in rows:
            name = str(row.get("secNm", "")).strip()
            try:
                q = float(str(row.get("applyQ", "0")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if q > 0 and _is_stock(name):
                holdings[name] = q
                tk = _ticker_from_code(str(row.get("itmNo", "")))
                if tk:
                    tickers[name] = tk
        if not holdings:
            return None, {}, {}
        gijun = pdf.get("gijunYMD", "")
        trd_dt = (f"{gijun[:4]}-{gijun[4:6]}-{gijun[6:8]}"
                 if len(gijun) == 8 else datetime.now(KST).strftime("%Y-%m-%d"))
        return trd_dt, holdings, tickers
    except Exception as e:
        logger.info(f"삼성액티브 공식 전종목 조회 실패: {e}")
        return None, {}, {}


# 종목코드(426030.KS 등) -> 공식 소스 fetch 함수
_FETCHERS = {
    "426030": lambda: fetch_timefolio_full("2"),
    "0015B0": lambda: fetch_samsung_full("2ETFQ1"),
}


def fetch_official_full(code: str):
    """code(예: '426030') -> (trd_dt, holdings, name_to_ticker) or (None, {}, {})."""
    fn = _FETCHERS.get(code)
    if not fn:
        return None, {}, {}
    return fn()
