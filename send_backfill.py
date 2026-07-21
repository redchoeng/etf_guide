# -*- coding: utf-8 -*-
"""7/20 놓친 대규모 매매 만회 발송 (1회성, 실행 후 삭제 예정)."""
import json
import subprocess
import sys

sys.path.insert(0, ".")
from alerts.holdings import diff_holdings, build_message, build_intent_lines, _ticker_of, _fetch_us_prices
from alerts.telegram import TelegramNotifier, report_kb


def load(ref):
    out = subprocess.run(["git", "show", f"{ref}:alerts/holdings_snapshot.json"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out)


def run():
    old_snap = load("daefcc9")  # 7/17 (마지막 신뢰 가능 시점)
    new_snap = load("HEAD")     # 최신

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        print("Telegram 미설정")
        return

    for code, name in [("426030", "TIMEFOLIO"), ("0015B0", "KoACT")]:
        o = old_snap[code]["holdings"]
        n = new_snap[code]["holdings"]
        added, removed, changed, base = diff_holdings(o, n)
        if not (added or removed or changed):
            print(f"{name}: 변동 없음, 스킵")
            continue

        header = f"⚠️ <b>[지연 감지] {name} 구성종목 변경</b> <i>(7/17→7/20 사이, 코드 개선 전 놓친 매매)</i>\n"
        body_lines = []
        for x, q in added[:4]:
            body_lines.append(f"🆕 편입: {x} ({q:,.0f}주)")
        for x in removed[:4]:
            body_lines.append(f"❌ 제외: {x}")
        for x, ov, nv, pct in changed[:12]:
            arrow = "▲" if pct > 0 else "▼"
            body_lines.append(f"{arrow} {x}: {ov:,.0f} → {nv:,.0f}주 ({pct:+.0f}%)")
        rest = max(0, len(changed) - 12)
        if rest:
            body_lines.append(f"…외 {rest}건")
        msg = header + "\n".join(body_lines)

        last_diff = {"from": "2026-07-17", "to": "2026-07-20",
                     "added": [[a, q] for a, q in added],
                     "removed": [[r, o.get(r, 0)] for r in removed],
                     "changed": [[c, ov, nv, p] for c, ov, nv, p in changed], "minor": 0}
        involved = sorted({_ticker_of(x[0]) for x in changed if _ticker_of(x[0])})
        prices = _fetch_us_prices(involved)
        intent = build_intent_lines(last_diff, prices)
        if intent:
            msg += "\n\n" + "\n".join(intent)

        ok = notifier.send_message(msg, reply_markup=report_kb())
        print(f"{name} 발송: {ok}")


if __name__ == "__main__":
    run()
