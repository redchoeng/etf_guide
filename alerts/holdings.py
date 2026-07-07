"""ETF 구성종목(CU) 수량 변동 감지.

소스: 네이버 금융 백엔드(wisereport) — 매 영업일 CU 구성내역이 주식수로 공시됨.
비중(%)은 주가에 따라 매일 흔들리는 노이즈라서, 매니저가 실제로
사고판 것만 잡히는 '수량(AGMT_STK_CNT)' 기준으로 비교한다.
"""

import json
import logging
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = Path(__file__).parent / "holdings_snapshot.json"
CU_URL = "https://navercomp.wisereport.co.kr/v2/ETF/index.aspx?cmp_cd={code}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
ROW_RE = re.compile(r'\{"TRD_DT":"([^"]+)","AGMT_STK_CNT":([\d.]+),"STK_NM_KOR":"([^"]+)"')

QTY_CHANGE_PCT = 5.0   # 이 % 이상 수량 변동만 알림 (CU 미세조정 노이즈 제거)
MAX_LINES = 14         # 텔레그램 메시지 줄 수 제한
DIGEST_TOP_N = 5       # 데일리 다이제스트에 보여줄 상위 종목 수

# 구성종목명 → 미국 티커 (구체적인 키워드가 먼저 오도록 순서 유지)
NAME2TICKER = [
    ("APPLIED OPTO", "AAOI"), ("APPLIED MATERIALS", "AMAT"), ("APPLOVIN", "APP"),
    ("NVIDIA", "NVDA"), ("INTEL", "INTC"), ("MICRON", "MU"), ("SANDISK", "SNDK"),
    ("WESTERN DIGITAL", "WDC"), ("LAM RESEARCH", "LRCX"), ("CREDO", "CRDO"),
    ("ADVANCED MICRO", "AMD"), ("MARVELL", "MRVL"), ("DELL", "DELL"),
    ("ALPHABET", "GOOGL"), ("COREWEAVE", "CRWV"), ("KLA", "KLAC"),
    ("BROADCOM", "AVGO"), ("MICROSOFT", "MSFT"), ("QUALCOMM", "QCOM"),
    ("TESLA", "TSLA"), ("VERTIV", "VRT"), ("TERADYNE", "TER"),
    ("SILICON MOTION", "SIMO"), ("BLOOM ENERGY", "BE"), ("ORACLE", "ORCL"),
    ("SEAGATE", "STX"), ("ASTERA", "ALAB"), ("TAIWAN SEMI", "TSM"),
    ("META PLATFORM", "META"), ("GE VERNOVA", "GEV"), ("LUMENTUM", "LITE"),
    ("ASML", "ASML"), ("ELI LILLY", "LLY"), ("APPLE", "AAPL"),
    ("SNOWFLAKE", "SNOW"), ("AMAZON", "AMZN"), ("ARM HOLDINGS", "ARM"),
    ("PALANTIR", "PLTR"), ("ROBINHOOD", "HOOD"), ("NEBIUS", "NBIS"),
    ("COINBASE", "COIN"), ("NETFLIX", "NFLX"), ("COSTCO", "COST"),
    ("CISCO", "CSCO"), ("ADOBE", "ADBE"), ("SHOPIFY", "SHOP"),
]


def _ticker_of(name: str):
    up = name.upper()
    for kw, tk in NAME2TICKER:
        if kw in up:
            return tk
    return None


def _is_stock(name: str) -> bool:
    """현금·선물·설정금 등 비주식 항목 제외."""
    up = name.upper()
    return ("현금" not in name and "설정" not in name
            and "INDEX" not in up and "MINI" not in up)


def fetch_cu(code: str):
    """(기준일, {종목명: 주식수}) 반환. 실패 시 (None, None)."""
    r = requests.get(CU_URL.format(code=code), headers=HEADERS, timeout=15)
    r.raise_for_status()
    rows = ROW_RE.findall(r.text)
    if not rows:
        return None, None
    trd_dt = rows[0][0]
    holdings = {}
    for dt, qty, name in rows:
        if dt != trd_dt or not _is_stock(name):
            continue
        q = float(qty)
        if q > 0:
            holdings[name.strip()] = q
    return trd_dt, holdings


def _load_snapshot() -> dict:
    if SNAPSHOT_FILE.exists():
        try:
            return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_snapshot(snap: dict):
    SNAPSHOT_FILE.write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def diff_holdings(old: dict, new: dict):
    """신규 편입 / 전량 제외 / 수량 변동(±QTY_CHANGE_PCT 이상)."""
    added = [(n, q) for n, q in new.items() if n not in old]
    removed = [n for n in old if n not in new]
    changed = []
    for n, q in new.items():
        o = old.get(n)
        if o and o > 0:
            pct = (q - o) / o * 100
            if abs(pct) >= QTY_CHANGE_PCT:
                changed.append((n, o, q, pct))
    changed.sort(key=lambda x: -abs(x[3]))
    return added, removed, changed


def build_message(display: str, trd_dt: str, added, removed, changed) -> str:
    lines = [f"🔁 <b>{display} 구성종목 변경</b> <i>({trd_dt})</i>"]
    for n, q in added:
        lines.append(f"🆕 편입: {n} ({q:,.0f}주)")
    for n in removed:
        lines.append(f"❌ 제외: {n}")
    for n, o, q, pct in changed:
        arrow = "▲" if pct > 0 else "▼"
        lines.append(f"{arrow} {n}: {o:,.0f} → {q:,.0f}주 ({pct:+.0f}%)")
    if len(lines) > MAX_LINES:
        hidden = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f"…외 {hidden}건"]
    return "\n".join(lines)


def _fetch_us_prices(tickers: list) -> dict:
    """{티커: (현재가, 전일등락%)} — yfinance 배치 조회."""
    import yfinance as yf
    out = {}
    if not tickers:
        return out
    try:
        px = yf.download(tickers, period="5d", auto_adjust=True, progress=False)["Close"]
        if hasattr(px, "columns"):
            for t in px.columns:
                s = px[t].dropna()
                if len(s) >= 2:
                    out[t] = (float(s.iloc[-1]), (float(s.iloc[-1]) / float(s.iloc[-2]) - 1) * 100)
        else:  # 단일 티커
            s = px.dropna()
            if len(s) >= 2:
                out[tickers[0]] = (float(s.iloc[-1]), (float(s.iloc[-1]) / float(s.iloc[-2]) - 1) * 100)
    except Exception as e:
        logger.warning(f"미국 시세 조회 실패: {e}")
    return out


def _diff_summary_lines(last_diff: dict) -> list:
    """저장된 최근 매매 내역 → 메시지 줄들."""
    if not last_diff:
        return ["🔁 매매: 비교 데이터 수집 중"]
    label = f"{last_diff.get('from', '?')}→{last_diff.get('to', '?')}"
    added = last_diff.get("added", [])
    removed = last_diff.get("removed", [])
    changed = last_diff.get("changed", [])
    minor = last_diff.get("minor", 0)
    if not (added or removed or changed):
        note = f" (미세조정 {minor}건)" if minor else ""
        return [f"🔁 매매({label}): 변동 없음{note}"]
    lines = [f"🔁 매매({label}):"]
    for n, q in added[:4]:
        lines.append(f"  🆕 편입 {n} ({q:,.0f}주)")
    for n in removed[:4]:
        lines.append(f"  ❌ 제외 {n}")
    for n, o, q, pct in changed[:5]:
        arrow = "▲" if pct > 0 else "▼"
        lines.append(f"  {arrow} {n} {o:,.0f}→{q:,.0f}주 ({pct:+.0f}%)")
    rest = max(0, len(added) - 4) + max(0, len(removed) - 4) + max(0, len(changed) - 5)
    if rest:
        lines.append(f"  …외 {rest}건")
    return lines


def build_daily_digest(entries: list, prices: dict) -> str:
    """매일 아침 구성종목 데일리 브리핑.

    entries: [{display, trd_dt, holdings, last_diff}]
    """
    date_label = entries[0]["trd_dt"] if entries else ""
    lines = [f"🧾 <b>구성종목 데일리</b> <i>({date_label} 기준)</i>"]
    for e in entries:
        # 추정 비중: 주식수 x 달러가 (매핑되는 종목만)
        vals = []
        for name, qty in e["holdings"].items():
            tk = _ticker_of(name)
            if tk and tk in prices:
                vals.append((tk, qty * prices[tk][0], prices[tk][1]))
        total = sum(v for _, v, _ in vals) or 1
        top = sorted(vals, key=lambda x: -x[1])[:DIGEST_TOP_N]
        lines.append("")
        lines.append(f"📌 <b>{e['display']}</b> — 상위 보유 (추정비중 · 전일)")
        for tk, v, chg in top:
            emoji = "🔺" if chg > 0.05 else ("🔻" if chg < -0.05 else "▪")
            lines.append(f"  {tk} {v / total * 100:.0f}% · {emoji}{chg:+.1f}%")
        lines.extend(_diff_summary_lines(e.get("last_diff")))
    return "\n".join(lines)


def check_holdings_changes(notifier, state: dict, presets: dict) -> int:
    """구성종목 수량 변동 체크 + 알림 + 데일리 브리핑. 발송 건수 반환.

    스냅샷은 holdings_snapshot.json에 저장되어 런 간 유지된다 (git 커밋).
    - 변동 알림: 기준일이 바뀌고 실제 매매(편입/제외/수량 5%+)가 있을 때 즉시
    - 데일리 브리핑: 매일 첫 실행 때 1건 (변동 없어도 발송)
    """
    from datetime import datetime, timezone, timedelta
    from alerts.state import _should_alert

    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).strftime("%Y-%m-%d")

    snap = _load_snapshot()
    sent = 0
    entries = []
    for ticker, preset in presets.items():
        code = ticker.split(".")[0]
        display = preset.get("display", ticker)
        try:
            trd_dt, holdings = fetch_cu(code)
        except Exception as e:
            logger.warning(f"  {display} 구성종목 조회 실패: {e}")
            continue
        if not holdings:
            logger.warning(f"  {display} 구성종목 데이터 없음")
            continue
        logger.info(f"  {display} 구성 {len(holdings)}종목 (기준일 {trd_dt})")

        prev = snap.get(code, {})
        old = prev.get("holdings")
        last_diff = prev.get("last_diff")
        # 기준일이 바뀌었을 때만 비교 (당일 재실행 스킵)
        if old and prev.get("date") != trd_dt:
            added, removed, changed = diff_holdings(old, holdings)
            minor = sum(
                1 for n, q in holdings.items()
                if n in old and old[n] > 0
                and 0 < abs((q - old[n]) / old[n] * 100) < QTY_CHANGE_PCT
            )
            last_diff = {
                "from": prev.get("date"), "to": trd_dt,
                "added": [[n, q] for n, q in added],
                "removed": removed,
                "changed": [[n, o, q, pct] for n, o, q, pct in changed],
                "minor": minor,
            }
            if (added or removed or changed) and _should_alert(f"holdings_{code}", state):
                msg = build_message(display, trd_dt, added, removed, changed)
                if notifier.send_message(msg):
                    sent += 1
                    logger.info(f"  🔁 {display} 구성 변경 알림 "
                                f"(편입 {len(added)} / 제외 {len(removed)} / 변동 {len(changed)})")

        snap[code] = {"date": trd_dt, "holdings": holdings, "last_diff": last_diff}
        entries.append({"display": display, "trd_dt": trd_dt,
                        "holdings": holdings, "last_diff": last_diff})

    # 데일리 브리핑 (하루 1번, 변동 없어도 발송)
    if entries and state.get("_alert_holdings_digest") != today:
        tickers = sorted({
            _ticker_of(n) for e in entries for n in e["holdings"] if _ticker_of(n)
        })
        prices = _fetch_us_prices(tickers)
        if prices:
            msg = build_daily_digest(entries, prices)
            if notifier.send_message(msg):
                state["_alert_holdings_digest"] = today
                sent += 1
                logger.info("  🧾 구성종목 데일리 브리핑 발송")

    _save_snapshot(snap)
    return sent
