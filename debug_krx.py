# -*- coding: utf-8 -*-
"""KRX PDF 응답 구조 확인용 (1회성 디버그, 확인 후 삭제)."""
import os
import sys

print("KRX_ID set:", bool(os.environ.get("KRX_ID")))
print("KRX_PW set:", bool(os.environ.get("KRX_PW")))

try:
    from pykrx import stock
    import pykrx
    print("pykrx version:", getattr(pykrx, "__version__", "?"))
except Exception as e:
    print("pykrx import 실패:", e)
    sys.exit(1)

for code in ("426030", "0015B0"):
    print(f"\n===== {code} =====")
    try:
        df = stock.get_etf_portfolio_deposit_file(code)
        print("shape:", df.shape)
        print("index name:", df.index.name, "| dtype:", df.index.dtype)
        print("columns:", list(df.columns))
        print(df.head(12).to_string())
    except Exception as e:
        print("조회 실패:", type(e).__name__, e)
