# -*- coding: utf-8 -*-
"""7/20 놓친 대규모 매매 만회 발송 (1회성, 실행 후 삭제 예정).

7/17 vs 7/20 스냅샷 비교 결과를 로컬에서 미리 계산해 하드코딩.
(얕은 클론 환경이라 git show로 옛 커밋을 못 읽어 방식 변경)
"""
import sys

sys.path.insert(0, ".")
from alerts.holdings import build_intent_lines, _ticker_of, _fetch_us_prices
from alerts.telegram import TelegramNotifier, report_kb

# (from daefcc9 7/17 -> HEAD 최신, diff_holdings 결과)
TIMEFOLIO_CHANGED = [
    ("META PLATFORMS INC-CLASS A", 12.0, 22.0, 83.3),
    ("COINBASE GLOBAL INC -CLASS A", 56.0, 97.0, 73.2),
    ("MICROSOFT CORP", 36.0, 53.0, 47.2),
    ("APPLE INC", 43.0, 63.0, 46.5),
    ("ALPHABET INC-CL A", 40.0, 58.0, 45.0),
    ("BROADCOM INC", 38.0, 55.0, 44.7),
    ("MARVELL TECHNOLOGY INC", 87.0, 53.0, -39.1),
    ("CORNING INC", 54.0, 34.0, -37.0),
    ("NVIDIA CORP", 177.0, 240.0, 35.6),
    ("WESTERN DIGITAL CORP", 40.0, 26.0, -35.0),
    ("ROBINHOOD MARKETS INC - A", 176.0, 234.0, 33.0),
    ("SEAGATE TECHNOLOGY HOLDINGS", 26.0, 18.0, -30.8),
    ("APPLIED OPTOELECTRONICS INC", 127.0, 94.0, -26.0),
    ("DELL TECHNOLOGIES -C", 66.0, 49.0, -25.8),
    ("ADVANCED MICRO DEVICES", 74.0, 61.0, -17.6),
]


def run():
    notifier = TelegramNotifier()
    if not notifier.is_configured:
        print("Telegram 미설정")
        return

    header = ("⚠️ <b>[지연 감지] TIMEFOLIO 구성종목 변경</b> "
              "<i>(7/17→7/20 사이, 코드 개선 전 놓친 매매)</i>\n")
    body_lines = []
    for x, ov, nv, pct in TIMEFOLIO_CHANGED:
        arrow = "▲" if pct > 0 else "▼"
        body_lines.append(f"{arrow} {x}: {ov:,.0f} → {nv:,.0f}주 ({pct:+.0f}%)")
    msg = header + "\n".join(body_lines)

    last_diff = {"from": "2026-07-17", "to": "2026-07-20", "added": [], "removed": [],
                 "changed": [[c, ov, nv, p] for c, ov, nv, p in TIMEFOLIO_CHANGED], "minor": 0}
    involved = sorted({_ticker_of(x[0]) for x in TIMEFOLIO_CHANGED if _ticker_of(x[0])})
    prices = _fetch_us_prices(involved)
    intent = build_intent_lines(last_diff, prices)
    if intent:
        msg += "\n\n" + "\n".join(intent)

    ok = notifier.send_message(msg, reply_markup=report_kb())
    print(f"발송: {ok}")


if __name__ == "__main__":
    run()
