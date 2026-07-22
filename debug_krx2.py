# -*- coding: utf-8 -*-
"""KRX PDF 요청의 실제 HTTP 응답 캡처 (1회성 디버그)."""
import os

from pykrx.website.comm.auth import get_auth_session
from pykrx.website.krx.etx.wrap import get_etx_isin

for code in ("426030", "0015B0"):
    print(f"\n===== {code} =====")
    krxs = get_auth_session()
    print("세션 유효:", krxs.is_valid() if krxs else None)

    isin = get_etx_isin(code)
    print("ISIN:", isin)

    date = __import__("time").strftime("%Y%m%d")
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT05001",
        "isuCd": isin,
        "trdDd": date,
    }
    headers = krxs.get_headers()
    headers["User-Agent"] = "Mozilla/5.0"
    resp = krxs.session.post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        headers=headers, data=payload, timeout=15,
    )
    print("status_code:", resp.status_code)
    print("response headers:", dict(resp.headers))
    print("body[:500]:", repr(resp.text[:500]))
