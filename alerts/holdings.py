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


def check_holdings_changes(notifier, state: dict, presets: dict) -> int:
    """구성종목 수량 변동 체크 + 알림. 발송 건수 반환.

    스냅샷은 holdings_snapshot.json에 저장되어 런 간 유지된다 (git 커밋).
    같은 ETF 알림은 하루 1번 (KST 날짜 dedup).
    """
    from alerts.state import _should_alert

    snap = _load_snapshot()
    sent = 0
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
        # 같은 기준일이면 비교 스킵 (당일 재실행)
        if old and prev.get("date") != trd_dt:
            added, removed, changed = diff_holdings(old, holdings)
            if (added or removed or changed) and _should_alert(f"holdings_{code}", state):
                msg = build_message(display, trd_dt, added, removed, changed)
                if notifier.send_message(msg):
                    sent += 1
                    logger.info(f"  🔁 {display} 구성 변경 알림 "
                                f"(편입 {len(added)} / 제외 {len(removed)} / 변동 {len(changed)})")
        snap[code] = {"date": trd_dt, "holdings": holdings}

    _save_snapshot(snap)
    return sent
