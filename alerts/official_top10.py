"""운용사 공식 사이트에서 상위 보유종목(top10) 직접 조회.

로그인 불필요, KRX 차단과 무관 — 운용사가 직접 공시하는 값이라 가장 정확하다.
단, 상위 10종목까지만 제공돼서 전종목 매매 감지(diff_holdings)는
여전히 alerts/holdings.py의 KRX/네이버 경로를 쓴다. 이 모듈은
데일리 브리핑의 "상위 보유" 표시 정확도를 높이는 용도.
"""

import logging
import re
import warnings

import requests
import urllib3

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# 타임폴리오(timeetf.co.kr) — HTML에 오늘자 top10이 인라인으로 렌더링됨
TF_URL = "https://timeetf.co.kr/m11_view.php?idx={idx}"
TF_ROW_RE = re.compile(
    r'<div class="name"><span>\d+</span>([^<]+)</div>\s*'
    r'<div>([\d.]+)%</div>\s*'
    r'<div><span class="(up|down)">([+-][\d.]+)%</span></div>'
)

# 삼성액티브(samsungactive.co.kr) — JSON API, bznsDt가 실제 기준일
SA_URL = "https://www.samsungactive.co.kr/api/v1/product/etf-pdf-top10/{fid}.do"


def fetch_timefolio_top10(idx: str = "2"):
    """타임폴리오 오늘자 top10. [(종목명, 비중%, 등락%)] 또는 None."""
    try:
        r = requests.get(TF_URL.format(idx=idx), headers=HEADERS, timeout=15, verify=False)
        r.raise_for_status()
        rows = TF_ROW_RE.findall(r.text)
        if not rows:
            return None
        out = []
        for name, wgt, direction, chg in rows:
            pct = float(chg) if direction == "up" else -abs(float(chg))
            out.append((name.strip(), float(wgt), pct))
        return out
    except Exception as e:
        logger.info(f"타임폴리오 공식 top10 조회 실패: {e}")
        return None


def fetch_samsung_top10(fid: str = "2ETFQ1"):
    """삼성액티브(KoACT) 오늘자 top10. (기준일, [(종목명, 비중%)]) 또는 (None, None)."""
    try:
        r = requests.get(
            SA_URL.format(fid=fid), headers=HEADERS, timeout=15,
            params={"period": 0, "searchType": "wgt"},
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("period") or []
        if not rows:
            return None, None
        bzns_dt = data.get("bznsDt", "")
        trd_dt = f"{bzns_dt[:4]}-{bzns_dt[4:6]}-{bzns_dt[6:8]}" if len(bzns_dt) == 8 else None
        out = [(row["secEngNm"].strip(), float(row["wgt"])) for row in rows if row.get("wgt")]
        return trd_dt, out
    except Exception as e:
        logger.info(f"삼성액티브 공식 top10 조회 실패: {e}")
        return None, None
