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

QTY_CHANGE_PCT = 3.0   # 정규화(공통 스케일 제거) 후 이 % 이상 실질 변동만 알림
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
    ("ANALOG DEVICES", "ADI"), ("TEXAS INSTRUMENTS", "TXN"),
]


# 공식 소스(official_holdings)가 응답에 실어주는 이름→티커 매핑을 여기 채워둔다.
# 하드코딩 테이블(NAME2TICKER)보다 항상 우선 — 운용사가 준 진짜 값이라서.
_DYNAMIC_TICKER_MAP: dict = {}


def _ticker_of(name: str):
    if name in _DYNAMIC_TICKER_MAP:
        return _DYNAMIC_TICKER_MAP[name]
    up = name.upper()
    for kw, tk in NAME2TICKER:
        if kw in up:
            return tk
    return None


# 매매 의도 해석용 테마 분류
THEMES = [
    ("반도체·HW", {"NVDA", "AMD", "AVGO", "ARM", "TSM", "MU", "SNDK", "WDC", "STX",
                   "INTC", "LRCX", "AMAT", "KLAC", "TER", "SIMO", "CRDO", "MRVL",
                   "ALAB", "AAOI", "LITE", "ASML", "DELL", "ADI", "TXN"}),
    ("AI·소프트웨어", {"PLTR", "SNOW", "MSFT", "GOOGL", "META", "APP", "ADBE",
                    "ORCL", "NFLX", "COIN", "HOOD", "SHOP", "NBIS", "CRWV"}),
    ("전력·인프라", {"BE", "GEV", "VRT"}),
    ("빅테크·소비", {"AAPL", "AMZN", "TSLA", "LLY", "COST", "PEP", "CSCO"}),
]


def _theme_of(tk: str) -> str:
    for name, s in THEMES:
        if tk in s:
            return name
    return "기타"


def _is_stock(name: str) -> bool:
    """현금·선물·설정금 등 비주식 항목 제외."""
    up = name.upper()
    return ("현금" not in name and "설정" not in name
            and "INDEX" not in up and "MINI" not in up)


def fetch_cu(code: str):
    """네이버(wisereport) CU. (기준일, {종목명: 주식수}) 반환. 실패 시 (None, None)."""
    import time

    for attempt in range(2):
        try:
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
        except Exception as e:
            if attempt == 0:
                logger.info(f"네이버 CU 재시도 {code}: {e}")
                time.sleep(2)
            else:
                logger.warning(f"네이버 CU 조회 실패 {code}: {e}")
                return None, None


def fetch_cu_krx(code: str, max_attempts: int = 4):
    """KRX 원본 공시 (pykrx 세션 재사용 + 직접 요청, KRX_ID/KRX_PW 필요).

    KRX는 개장 전에 당일 PDF를 공시하므로 네이버보다 반나절 빠르다.
    (기준일=오늘 KST, {종목명: 계약수}) 반환. 미설정/실패 시 (None, None).

    실측 결과 KRX 서버가 이 리포트(MDCSTAT05001)에 장중(특히 오전 11시
    이후)엔 45초를 줘도 응답을 아예 안 주는 경우가 잦다(ReadTimeout).
    타임아웃 문제가 아니라 서버 쪽 가용성 문제로 보인다 — 개장 전에는
    안정적으로 응답했다. max_attempts로 시간대별 재시도 강도를 조절한다.
    """
    import os
    import time
    from datetime import datetime, timezone, timedelta

    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        return None, None

    MAX_ATTEMPTS = max_attempts
    for attempt in range(MAX_ATTEMPTS):
        try:
            from pykrx.website.comm.auth import get_auth_session
            from pykrx.website.krx.etx.wrap import get_etx_isin

            krxs = get_auth_session()
            if krxs is None:
                raise ValueError("KRX 인증 세션 없음")
            isin = get_etx_isin(code)
            trd_dt = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
            headers = krxs.get_headers()
            headers["User-Agent"] = "Mozilla/5.0"
            resp = krxs.session.post(
                "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                headers=headers,
                data={"bld": "dbms/MDC/STAT/standard/MDCSTAT05001",
                      "isuCd": isin, "trdDd": trd_dt},
                timeout=45,
            )
            data = resp.json()
            rows = data.get("output") or []
            if not rows:
                raise ValueError("empty response")
            holdings = {}
            for row in rows:
                name = str(row.get("COMPST_ISU_NM", "")).strip()
                try:
                    q = float(str(row.get("COMPST_ISU_CU1_SHRS", "0")).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if q > 0 and _is_stock(name):
                    holdings[name] = q
            if not holdings:
                raise ValueError("no holdings parsed")
            kst_today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            return kst_today, holdings
        except Exception as e:
            if attempt < MAX_ATTEMPTS - 1:
                logger.info(f"KRX PDF 재시도 {code} ({attempt + 1}/{MAX_ATTEMPTS}): {e}")
                time.sleep(5)
            else:
                logger.warning(f"KRX PDF 조회 실패 {code}: {e}")
    return None, None


def fetch_cu_best(code: str, krx_attempts: int = 1):
    """(기준일, {종목명: 수량}, 소스) — 운용사 공식 사이트가 메인.

    순서: ① 운용사 공식(로그인 불필요, 전종목, 티커 포함, 가장 안정적)
          ② KRX(2025-12-27부터 비공식 클라이언트 차단 중이라 거의 항상 실패)
          ③ 네이버(최종 폴백)
    """
    from alerts.official_holdings import fetch_official_full

    trd_dt, holdings, name_to_ticker = fetch_official_full(code)
    if holdings:
        _DYNAMIC_TICKER_MAP.update(name_to_ticker)
        return trd_dt, holdings, "official"

    trd_dt, holdings = fetch_cu_krx(code, max_attempts=krx_attempts)
    if holdings:
        return trd_dt, holdings, "krx"

    trd_dt, holdings = fetch_cu(code)
    return trd_dt, holdings, "naver"


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
    """신규 편입 / 전량 제외 / 실질 수량 변동.

    설정단위(CU) 재계산으로 전 종목 수량이 같은 비율로 흔들리는 날이 있어서,
    공통 스케일(비율 중앙값)을 제거한 '실질 변동'으로 판정한다.
    반환: (added, removed, changed, base) — changed의 pct는 정규화된 실질 %.
    """
    import statistics

    added = [(n, q) for n, q in new.items() if n not in old]
    removed = [n for n in old if n not in new]
    ratios = [new[n] / old[n] for n in new if n in old and old[n] > 0]
    base = statistics.median(ratios) if ratios else 1.0
    if base <= 0:
        base = 1.0
    changed = []
    for n, q in new.items():
        o = old.get(n)
        if o and o > 0:
            adj = (q / o) / base * 100 - 100
            if abs(adj) >= QTY_CHANGE_PCT:
                changed.append((n, o, q, adj))
    changed.sort(key=lambda x: -abs(x[3]))
    return added, removed, changed, base


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
    """{티커: (현재가, 전일등락%, 1개월수익률%)} — yfinance 배치 조회."""
    import yfinance as yf
    out = {}
    if not tickers:
        return out

    def _add(t, s):
        s = s.dropna()
        if len(s) >= 2:
            last = float(s.iloc[-1])
            day = (last / float(s.iloc[-2]) - 1) * 100
            mom = (last / float(s.iloc[0]) - 1) * 100
            out[t] = (last, day, mom)

    try:
        px = yf.download(tickers, period="1mo", auto_adjust=True, progress=False)["Close"]
        if hasattr(px, "columns"):
            for t in px.columns:
                _add(t, px[t])
        else:  # 단일 티커
            _add(tickers[0], px)
    except Exception as e:
        logger.warning(f"미국 시세 조회 실패: {e}")
    return out


def build_intent_lines(last_diff: dict, prices: dict) -> list:
    """매매 의도 추정 (규칙 기반).

    수량 변화 방향 x 해당 종목의 최근 1개월 주가 흐름으로 분류:
      늘림+하락 = 저가 매수 / 늘림+상승 = 추세 확대
      줄임+상승 = 차익 실현 / 줄임+하락 = 리스크 축소
    """
    if not last_diff:
        return []
    trades = []  # (설명, 거래대금 추정)
    theme_net = {}

    def _note(tk, delta_value, label):
        theme = _theme_of(tk)
        theme_net[theme] = theme_net.get(theme, 0) + delta_value
        trades.append((f"{tk} {label}", abs(delta_value)))

    for item in last_diff.get("added", []):
        n, q = item[0], item[1]
        tk = _ticker_of(n)
        if tk and tk in prices:
            _note(tk, q * prices[tk][0], "신규 진입")
    for item in last_diff.get("removed", []):
        n = item[0] if isinstance(item, (list, tuple)) else item
        oq = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else 0
        tk = _ticker_of(n)
        if tk and tk in prices:
            _note(tk, -oq * prices[tk][0], "전량 정리")
    for n, o, q, pct in last_diff.get("changed", []):
        tk = _ticker_of(n)
        if not (tk and tk in prices):
            continue
        price, _day, mom = prices[tk]
        dv = (q - o) * price
        if dv > 0:
            label = "저가 매수 추정" if mom < -3 else "비중 확대"
        else:
            label = "차익 실현 추정" if mom > 3 else "비중 축소"
        _note(tk, dv, label)

    if not trades:
        return []

    # 테마 방향 요약 (유의미한 것만)
    sig = [(t, v) for t, v in theme_net.items() if abs(v) > 0]
    sig.sort(key=lambda x: -abs(x[1]))
    inc = [t for t, v in sig if v > 0][:2]
    dec = [t for t, v in sig if v < 0][:2]
    parts = []
    if inc:
        parts.append(" / ".join(inc) + " 확대")
    if dec:
        parts.append(" / ".join(dec) + " 축소")
    theme_line = ", ".join(parts) if parts else "테마 변화 미미"

    trades.sort(key=lambda x: -x[1])
    detail = " · ".join(d for d, _ in trades[:3])
    return [f"💡 의도 읽기: {theme_line}", f"   {detail}"]


def _diff_summary_lines(last_diff: dict) -> list:
    """저장된 최근 매매 내역 → 메시지 줄들."""
    if not last_diff:
        return ["🔁 매매: 비교 데이터 수집 중"]
    label = f"{last_diff.get('from', '?')}→{last_diff.get('to', '?')}"
    added = last_diff.get("added", [])
    removed = last_diff.get("removed", [])
    changed = last_diff.get("changed", [])
    minor = last_diff.get("minor", 0)
    small = last_diff.get("small") or []

    def _small_line():
        parts = []
        for item in small[:6]:
            n, _o, _q, adj = item
            tk = _ticker_of(n) or n[:10]
            parts.append(f"{tk} {adj:+.1f}%")
        more = f" 외{len(small) - 6}" if len(small) > 6 else ""
        return f"  〰 소폭: {' · '.join(parts)}{more}"

    if not (added or removed or changed):
        if small:
            return [f"🔁 매매({label}): 큰 변동 없음", _small_line()]
        note = f" (미세조정 {minor}건)" if minor else ""
        return [f"🔁 매매({label}): 변동 없음{note}"]
    lines = [f"🔁 매매({label}):"]
    for n, q in added[:4]:
        lines.append(f"  🆕 편입 {n} ({q:,.0f}주)")
    for item in removed[:4]:
        n = item[0] if isinstance(item, (list, tuple)) else item
        lines.append(f"  ❌ 제외 {n}")
    for n, o, q, pct in changed[:5]:
        arrow = "▲" if pct > 0 else "▼"
        lines.append(f"  {arrow} {n} {o:,.0f}→{q:,.0f}주 ({pct:+.0f}%)")
    rest = max(0, len(added) - 4) + max(0, len(removed) - 4) + max(0, len(changed) - 5)
    if rest:
        lines.append(f"  …외 {rest}건")
    if small:
        lines.append(_small_line())
    return lines


def _official_top10(ticker: str):
    """운용사 공식 사이트 top10 (로그인 불필요, 가장 정확).

    [(종목명, 비중%, 등락% 또는 None)] 또는 실패 시 None.
    매매 감지엔 안 쓴다 — top10까지만 커버해서 diff 판정용으로는 부족.
    """
    from alerts.official_top10 import fetch_timefolio_top10, fetch_samsung_top10

    code = ticker.split(".")[0]
    try:
        if code == "426030":
            return fetch_timefolio_top10("2")
        if code == "0015B0":
            _dt, rows = fetch_samsung_top10("2ETFQ1")
            return [(n, w, None) for n, w in rows] if rows else None
    except Exception as e:
        logger.info(f"공식 top10 조회 실패 {ticker}: {e}")
    return None


def build_daily_digest(entries: list, prices: dict) -> str:
    """매일 아침 구성종목 데일리 브리핑.

    entries: [{display, trd_dt, holdings, last_diff, ticker}]
    상위 보유 표시는 운용사 공식 top10(정확) 우선, 실패 시 KRX/네이버
    전종목 수량 x yfinance 가격 추정치로 폴백. 매매 감지(last_diff)는
    항상 전종목 비교 결과를 그대로 쓴다 — 여기서 손대지 않는다.
    """
    date_label = entries[0]["trd_dt"] if entries else ""
    lines = [f"🧾 <b>구성종목 데일리</b> <i>({date_label} 기준)</i>"]
    for e in entries:
        official = _official_top10(e.get("ticker", ""))
        lines.append("")
        if official:
            lines.append(f"📌 <b>{e['display']}</b> — 상위 보유 (공식 비중)")
            for name, wgt, chg in official[:DIGEST_TOP_N]:
                tk = _ticker_of(name) or name[:14]
                if chg is None:
                    lines.append(f"  {tk} {wgt:.1f}%")
                else:
                    emoji = "🔺" if chg > 0.05 else ("🔻" if chg < -0.05 else "▪")
                    lines.append(f"  {tk} {wgt:.1f}% · {emoji}{chg:+.1f}%")
        else:
            # 폴백: 전종목 수량 x 가격 추정 (기존 방식)
            vals = []
            for name, qty in e["holdings"].items():
                tk = _ticker_of(name)
                if tk and tk in prices:
                    vals.append((tk, qty * prices[tk][0], prices[tk][1]))
            total = sum(v for _, v, _ in vals) or 1
            top = sorted(vals, key=lambda x: -x[1])[:DIGEST_TOP_N]
            lines.append(f"📌 <b>{e['display']}</b> — 상위 보유 (추정비중 · 전일)")
            for tk, v, chg in top:
                emoji = "🔺" if chg > 0.05 else ("🔻" if chg < -0.05 else "▪")
                lines.append(f"  {tk} {v / total * 100:.0f}% · {emoji}{chg:+.1f}%")
        lines.extend(_diff_summary_lines(e.get("last_diff")))
        lines.extend(build_intent_lines(e.get("last_diff"), prices))
    return "\n".join(lines)


def check_holdings_changes(notifier, state: dict, presets: dict, krx_attempts: int = 1) -> int:
    """구성종목 수량 변동 체크 + 알림 + 데일리 브리핑. 발송 건수 반환.

    스냅샷은 holdings_snapshot.json에 저장되어 런 간 유지된다 (git 커밋).
    - 변동 알림: 기준일이 바뀌고 실제 매매(편입/제외/수량 5%+)가 있을 때 즉시
    - 데일리 브리핑: 매일 첫 실행 때 1건 (변동 없어도 발송)

    krx_attempts: KRX가 차단 중이라 대부분 시간대엔 1회만 찔러보고 네이버로
    넘어간다. 개장 전(08:30 장전 브리핑)만 성공률이 있어 호출부에서 높여 줌.
    """
    import time
    from datetime import datetime, timezone, timedelta
    from alerts.state import _should_alert

    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).strftime("%Y-%m-%d")

    snap = _load_snapshot()
    sent = 0
    entries = []
    for i, (ticker, preset) in enumerate(presets.items()):
        code = ticker.split(".")[0]
        display = preset.get("display", ticker)
        if i > 0:
            time.sleep(2)
        try:
            trd_dt, holdings, src = fetch_cu_best(code, krx_attempts=krx_attempts)
        except Exception as e:
            logger.warning(f"  {display} 구성종목 조회 실패: {e}")
            continue
        if not holdings:
            logger.warning(f"  {display} 구성종목 데이터 없음")
            continue
        logger.info(f"  {display} 구성 {len(holdings)}종목 (기준일 {trd_dt}, 소스 {src})")

        prev = snap.get(code, {})
        old = prev.get("holdings")
        last_diff = prev.get("last_diff")
        # 소스가 바뀌면 종목명 표기가 달라 가짜 diff가 나므로 재베이스라인
        if old and prev.get("src") and prev.get("src") != src:
            logger.info(f"  {display} 소스 전환({prev.get('src')}→{src}) — 재베이스라인")
            old = None
        # 내용 기반 비교 — 매 실행마다 diff.
        # (KRX 데이터가 같은 날 늦게 갱신되는 경우가 있어 날짜 라벨 비교는 매매를
        #  조용히 흡수해버림. 내용이 같으면 diff가 비어서 어차피 무해함.)
        if old:
            added, removed, changed, base = diff_holdings(old, holdings)
            has_real = bool(added or removed or changed)
            # 소폭 매매 (0.5% ~ 기준치): 알림은 안 울리지만 데일리에 표시
            small = sorted(
                ((n, old[n], q, (q / old[n]) / base * 100 - 100)
                 for n, q in holdings.items()
                 if n in old and old[n] > 0
                 and 0.5 <= abs((q / old[n]) / base * 100 - 100) < QTY_CHANGE_PCT),
                key=lambda x: -abs(x[3]))
            # 실질 변동이 있거나 기준일이 넘어갔을 때만 last_diff 갱신
            # (빈 diff로 전날의 매매 기록을 덮어쓰지 않도록)
            if has_real or small or prev.get("date") != trd_dt:
                last_diff = {
                    "from": prev.get("date"), "to": trd_dt,
                    "added": [[n, q] for n, q in added],
                    "removed": [[n, old.get(n, 0)] for n in removed],
                    "changed": [[n, o, q, pct] for n, o, q, pct in changed],
                    "small": [[n, o, q, adj] for n, o, q, adj in small[:10]],
                    "minor": len(small),
                }
            if has_real and _should_alert(f"holdings_{code}", state):
                msg = build_message(display, trd_dt, added, removed, changed)
                # 매매 의도 해석 붙이기 (관련 종목 시세만 소량 조회)
                try:
                    involved = sorted({
                        _ticker_of(n) for n in
                        ([a[0] for a in added] + removed + [c[0] for c in changed])
                        if _ticker_of(n)
                    })
                    intent = build_intent_lines(last_diff, _fetch_us_prices(involved))
                    if intent:
                        msg += "\n\n" + "\n".join(intent)
                except Exception as e:
                    logger.debug(f"의도 해석 스킵: {e}")
                if notifier.send_message(msg):
                    sent += 1
                    logger.info(f"  🔁 {display} 구성 변경 알림 "
                                f"(편입 {len(added)} / 제외 {len(removed)} / 변동 {len(changed)})")

        snap[code] = {"date": trd_dt, "holdings": holdings,
                      "last_diff": last_diff, "src": src}
        entries.append({"display": display, "trd_dt": trd_dt, "ticker": ticker,
                        "holdings": holdings, "last_diff": last_diff})

    # 데일리 브리핑 (하루 1번, 변동 없어도 발송)
    # 네이버 데이터가 오늘 기준일로 갱신된 뒤에 발송해야 어제 매매분이 담긴다.
    # 11시(KST)까지 갱신이 안 되면 있는 데이터로라도 발송 (비상 폴백).
    if entries and state.get("_alert_holdings_digest") != today:
        fresh = all(e["trd_dt"] == today for e in entries)
        if fresh or datetime.now(KST).hour >= 11:
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
        else:
            logger.info("  🧾 데일리 브리핑 대기 (기준일 아직 전일)")

    _save_snapshot(snap)
    return sent
