#!/usr/bin/env python
"""
우당탕탕 딩쵱 하우스 마련 대작전 HTML 리포트 생성기.

GitHub Actions에서 자동 실행되어 사용자용 HTML 리포트를 생성합니다.
stock-recommendations 2.0 스타일 디자인.

v3: 무한매수법 — 매수만, 익절 없음. 매크로(VIX/금리) 연동, 그리드 분할매수 + 장기 보유
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

import yaml
import numpy as np

from engine.data_fetcher import ETFDataFetcher
from engine.signal_generator import SignalGenerator
from engine.grid_calculator import GridCalculator
from engine.macro_analyzer import MacroAnalyzer

KST = timezone(timedelta(hours=9))

# 레짐별 전략 파라미터
REGIME_ALLOCATION = {
    "BULL_STRONG": 0.75,  # 투자비율 75%, 예비금 25%
    "BULL":        0.70,
    "SIDEWAYS":    0.55,
    "CORRECTION":  0.50,
    "BEAR":        0.45,
    "CRISIS":      0.40,
}

STOP_LOSS_PCT = -50.0      # 손절 기준 (-50%)


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_presets():
    preset_path = Path(__file__).parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def analyze_etf(ticker: str, preset: dict, config: dict, macro: dict) -> dict | None:
    """단일 ETF 종합 분석 (매크로 환경 포함)."""
    try:
        fetcher = ETFDataFetcher(config.get("data", {}))
        signal_gen = SignalGenerator(config.get("signals", {}))

        df = fetcher.fetch_history(ticker, period="1y")
        if df is None or df.empty or len(df) < 60:
            return None

        close = df["Close"]
        current_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])
        change_pct = (current_price - prev_price) / prev_price * 100

        # 시그널
        signals = signal_gen.generate_signals(df)
        overall = signals.get("overall_signal", "HOLD")
        strength = signals.get("signal_strength", 0)
        rsi = signals.get("rsi_14", 50)

        # 낙폭
        high = close.cummax()
        drawdown_pct = float(((close.iloc[-1] - high.iloc[-1]) / high.iloc[-1]) * 100)
        ath = float(high.max())

        # 변동성
        returns = close.pct_change().dropna()
        vol_annual = float(returns.std() * np.sqrt(252) * 100)

        # SMA
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else sma50

        # 모멘텀 (1개월/3개월 수익률)
        mom_1m = (current_price / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
        mom_3m = (current_price / float(close.iloc[-66]) - 1) * 100 if len(close) >= 66 else 0

        # 추세 강도 (SMA 정배열 여부)
        trend_aligned = sma20 > sma50 > sma200 if len(close) >= 200 else sma20 > sma50

        # 매수 점수 (100점 만점) - 매크로 + 모멘텀 포함
        score = calculate_score(
            rsi, drawdown_pct, current_price, sma20, sma50, sma200,
            vol_annual, strength, macro, mom_1m, trend_aligned,
        )

        # 그리드 계산 (레짐별 투자비율)
        regime = macro.get("regime", "SIDEWAYS")
        allocation = REGIME_ALLOCATION.get(regime, 0.55)
        budget = preset.get("suggested_budget", 10000)
        grid_budget = budget * allocation
        reserve_budget = budget * (1 - allocation)

        gc = GridCalculator(config.get("grid", {}))
        grid = gc.calculate_grid(
            reference_price=current_price,
            total_budget=grid_budget,
            num_levels=preset.get("suggested_levels", 10),
            spacing_pct=preset.get("suggested_spacing", 5.0),
            weighting="linear",
        )

        next_buy = None
        for gl in grid:
            if gl.target_price < current_price:
                next_buy = gl
                break

        # 52주
        high_52w = float(close.max())
        low_52w = float(close.min())
        pos_52w = (current_price - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50

        # 손절 가격
        stop_loss_price = current_price * (1 + STOP_LOSS_PCT / 100)

        # 판정 텍스트
        verdict, verdict_detail = get_verdict(
            score, overall, drawdown_pct, rsi, next_buy, current_price,
            macro, mom_1m, trend_aligned,
        )

        return {
            "ticker": ticker,
            "name": preset.get("name", ticker),
            "underlying": preset.get("underlying", ""),
            "leverage": preset.get("leverage", 2),
            "category": preset.get("category", ""),
            "price": current_price,
            "change_pct": change_pct,
            "signal": overall,
            "strength": strength,
            "score": score,
            "rsi": rsi,
            "drawdown_pct": drawdown_pct,
            "ath": ath,
            "vol_annual": vol_annual,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "mom_1m": mom_1m,
            "mom_3m": mom_3m,
            "trend_aligned": trend_aligned,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pos_52w": pos_52w,
            "grid_levels": grid,
            "next_buy": next_buy,
            "total_budget": budget,
            "grid_budget": grid_budget,
            "reserve_budget": reserve_budget,
            "stop_loss_price": stop_loss_price,
            "verdict": verdict,
            "verdict_detail": verdict_detail,
            "allocation": allocation,
        }
    except Exception as e:
        print(f"  {ticker} 분석 실패: {e}")
        return None


def calculate_score(rsi, drawdown_pct, price, sma20, sma50, sma200,
                    vol, strength, macro, mom_1m, trend_aligned):
    """매수 매력도 점수 (100점 만점).

    - 가격 위치 (20점): 낙폭 OR 모멘텀 (시장 환경에 따라)
    - 기술적 (20점): RSI, SMA 지지/추세
    - 변동성 (10점): 안정적일수록 높음
    - 매크로 (20점): VIX, 금리, 시장 환경
    - 복합 시그널 (15점): signal_generator
    - 모멘텀 (15점): 상승장 보너스, 추세 강도
    """
    score = 0
    regime = macro.get("regime", "SIDEWAYS")

    # === 가격 위치 (20점) ===
    # 하락장: 낙폭 깊을수록 점수 높음
    # 상승장: 풀백(단기 조정) 시 점수 높음
    dd = abs(drawdown_pct)
    if regime in ("BEAR", "CRISIS", "CORRECTION"):
        # 하락장 모드: 낙폭 기반
        if dd >= 40:
            score += 20
        elif dd >= 30:
            score += 17
        elif dd >= 20:
            score += 14
        elif dd >= 10:
            score += 10
        elif dd >= 5:
            score += 6
        else:
            score += 2
    else:
        # 상승장/횡보장 모드: 풀백 + 낙폭 혼합
        if dd >= 15:
            score += 18  # 상승장에서 큰 낙폭 = 기회
        elif dd >= 10:
            score += 15
        elif dd >= 5:
            score += 10
        elif mom_1m < -5:
            score += 14  # 단기 급락 풀백
        elif mom_1m < -2:
            score += 10  # 약한 풀백
        elif mom_1m < 0:
            score += 7   # 미세 조정
        else:
            score += 4   # 고점 순항

    # === 기술적 (20점) ===
    # RSI (10점)
    if rsi < 25:
        score += 10
    elif rsi < 30:
        score += 9
    elif rsi < 40:
        score += 7
    elif rsi < 50:
        score += 5
    elif rsi < 55:
        score += 4  # 중립 ~ 약간 높음도 괜찮음
    elif rsi < 65:
        score += 2
    elif rsi < 70:
        score += 1

    # SMA/추세 (10점)
    if regime in ("BEAR", "CRISIS"):
        # 하락장: SMA 아래일수록 매수 매력
        if price < sma200:
            score += 10
        elif price < sma50:
            score += 7
        elif price < sma20:
            score += 4
        else:
            score += 1
    else:
        # 상승장: SMA 정배열 + 지지 확인
        if trend_aligned and price > sma20:
            score += 9  # 완벽한 상승 추세
        elif trend_aligned and price > sma50:
            score += 8  # 추세 유지 + SMA50 지지
        elif price > sma200:
            score += 6  # 장기 추세 위
        elif price > sma50:
            score += 4
        else:
            score += 2  # 추세 약화

    # === 변동성 (10점) ===
    if vol <= 25:
        score += 10
    elif vol <= 35:
        score += 8
    elif vol <= 45:
        score += 5
    elif vol <= 55:
        score += 3
    else:
        score += 1

    # === 매크로 (20점) ===
    macro_score = macro.get("macro_score", 0.5)
    score += int(macro_score * 20)

    # === 복합 시그널 (15점) ===
    score += int(strength * 15)

    # === 모멘텀 보너스 (15점) ===
    if regime in ("BULL", "BULL_STRONG"):
        # 상승장에서 모멘텀 점수
        if trend_aligned:
            score += 6  # 정배열 보너스
        if mom_1m > 5:
            score += 3  # 강한 상승 모멘텀
        elif mom_1m > 0:
            score += 5  # 건강한 상승
        elif mom_1m > -3:
            score += 7  # 상승장 풀백 = 매수 타이밍
        else:
            score += 4  # 큰 풀백
        # 3개월 추세
        if 0 < mom_1m < 8:
            score += 2  # 과열 아닌 상승
    elif regime in ("CORRECTION", "BEAR", "CRISIS"):
        # 하락장에서: 반등 시그널 체크
        if mom_1m > 3:
            score += 8  # 반등 시작 시그널
        elif mom_1m > 0:
            score += 5  # 바닥 다지기
        elif dd >= 30:
            score += 7  # 극단적 낙폭 = 역발상
        else:
            score += 3
    else:
        # 횡보장
        if mom_1m < -3:
            score += 8  # 횡보에서 하락 = 기회
        elif abs(mom_1m) < 2:
            score += 5  # 안정적 횡보
        else:
            score += 3

    return min(score, 100)


def get_verdict(score, signal, drawdown_pct, rsi, next_buy, price,
                macro, mom_1m, trend_aligned):
    """사용자용 판정 + 상세 설명 (상승장 대응 포함)."""
    regime = macro.get("regime", "SIDEWAYS")
    regime_kr = macro.get("regime_kr", "")

    if score >= 75:
        verdict = "적극 매수 추천"
        if regime in ("BEAR", "CRISIS"):
            detail = f"[{regime_kr}] ATH 대비 {drawdown_pct:.0f}% 하락. 역사적 저점 영역입니다. 그리드 매수를 적극 실행하되 예비금을 꼭 남기세요."
        elif regime in ("BULL", "BULL_STRONG"):
            detail = f"[{regime_kr}] 상승 추세에서 매수 적기입니다. 소량씩 분할매수하세요."
        else:
            detail = "복합 시그널이 강한 매수를 가리킵니다. 분할매수 실행을 추천합니다."
    elif score >= 60:
        verdict = "매수 고려"
        if regime in ("BULL", "BULL_STRONG") and mom_1m < 0:
            detail = f"[{regime_kr}] 상승장에서 {mom_1m:.1f}% 풀백 중. SMA 지지 확인 후 매수 적기."
        elif regime in ("BULL", "BULL_STRONG"):
            detail = f"[{regime_kr}] 추세 양호. 소량 분할매수 또는 다음 풀백 대기."
        elif next_buy:
            gap = (next_buy.target_price - price) / price * 100
            detail = f"[{regime_kr}] 다음 그리드 레벨(${next_buy.target_price:.2f})까지 {abs(gap):.1f}% 남았습니다."
        else:
            detail = f"[{regime_kr}] 시그널 양호. 소량 분할매수를 시작해볼 만합니다."
    elif score >= 40:
        verdict = "관망"
        if regime in ("BULL_STRONG",) and drawdown_pct > -5:
            detail = f"[{regime_kr}] 고점 근처. 3~5% 풀백 시 진입하세요. 조급할 필요 없습니다."
        elif rsi > 65:
            detail = f"[{regime_kr}] RSI {rsi:.0f} 과매수 접근. 추가 매수보다 대기가 유리합니다."
        else:
            detail = f"[{regime_kr}] 뚜렷한 시그널 없음. 가격 변동 관찰 후 진입하세요."
    else:
        verdict = "대기"
        if regime in ("BULL_STRONG",) and drawdown_pct > -3:
            detail = f"[{regime_kr}] ATH 근처 과열 상태. 조정을 기다려 더 좋은 가격에 진입하세요."
        elif rsi > 70:
            detail = f"[{regime_kr}] RSI {rsi:.0f} 과매수. 단기 조정 가능성 높음. 기다리세요."
        else:
            detail = f"[{regime_kr}] 매수 조건 미충족. 조정을 기다리세요."

    return verdict, detail


def verdict_color(score):
    if score >= 75:
        return "#2E7D32", "#E8F5E9", "#4CAF50"
    elif score >= 60:
        return "#1565C0", "#E3F2FD", "#2196F3"
    elif score >= 40:
        return "#E65100", "#FFF3E0", "#FF9800"
    else:
        return "#C62828", "#FFEBEE", "#F44336"


def regime_color(regime):
    return {
        "BULL_STRONG": ("#1B5E20", "#E8F5E9", "🚀"),
        "BULL": ("#2E7D32", "#E8F5E9", "📈"),
        "SIDEWAYS": ("#E65100", "#FFF3E0", "➡️"),
        "CORRECTION": ("#BF360C", "#FBE9E7", "📉"),
        "BEAR": ("#B71C1C", "#FFEBEE", "🐻"),
        "CRISIS": ("#4A148C", "#F3E5F5", "🔥"),
    }.get(regime, ("#5D4E37", "#FFF8DC", "❓"))


def signal_emoji(score_or_signal):
    if isinstance(score_or_signal, (int, float)):
        if score_or_signal >= 75:
            return "🟢"
        elif score_or_signal >= 60:
            return "🔵"
        elif score_or_signal >= 40:
            return "🟡"
        else:
            return "🟠"
    return {"STRONG_BUY": "🟢", "BUY": "🔵", "HOLD": "🟡", "WAIT": "🟠"}.get(score_or_signal, "⚪")


def generate_html(results: list[dict], macro: dict, now: datetime) -> str:
    """토스 스타일 사용자용 HTML 리포트."""
    total = len(results)
    buy_count = len([r for r in results if r["score"] >= 60])
    avg_score = sum(r["score"] for r in results) / total if total else 0
    best = max(results, key=lambda x: x["score"]) if results else None

    regime = macro.get("regime", "SIDEWAYS")
    regime_kr = macro.get("regime_kr", "")
    rc, rbg, remoji = regime_color(regime)
    vix = macro.get("vix", 20)
    rate = macro.get("rate_10y", 4.0)
    macro_desc = macro.get("description", "")

    results.sort(key=lambda x: x["score"], reverse=True)

    sp500_1m = macro.get("sp500_trend", {}).get("change_1m", 0)
    macro_pct = macro.get("macro_score", 0.5)
    allocation = REGIME_ALLOCATION.get(regime, 0.55)

    # 알림 데이터 생성
    noti_items = []
    noti_js_arr = []
    for r in results:
        if r["score"] >= 70:
            noti_items.append(("buy", f"<b>{r['ticker']}</b> 매수 점수 {r['score']}점 — 적극 매수 구간"))
            noti_js_arr.append(f'{{"type":"buy","ticker":"{r["ticker"]}","msg":"{r["ticker"]} {r["score"]}점 — 적극 매수 구간"}}')
        elif r["score"] >= 60:
            noti_items.append(("buy", f"<b>{r['ticker']}</b> 매수 점수 {r['score']}점 — 매수 고려"))
            noti_js_arr.append(f'{{"type":"buy","ticker":"{r["ticker"]}","msg":"{r["ticker"]} {r["score"]}점 — 매수 고려"}}')
        if r["rsi"] < 30:
            noti_items.append(("warn", f"<b>{r['ticker']}</b> RSI {r['rsi']:.0f} — 과매도 진입"))
            noti_js_arr.append(f'{{"type":"warn","ticker":"{r["ticker"]}","msg":"{r["ticker"]} RSI {r["rsi"]:.0f} 과매도"}}')
        if r["drawdown_pct"] <= -25:
            noti_items.append(("warn", f"<b>{r['ticker']}</b> 낙폭 {r['drawdown_pct']:.1f}% — 그리드 하위 레벨 도달"))
            noti_js_arr.append(f'{{"type":"warn","ticker":"{r["ticker"]}","msg":"{r["ticker"]} 낙폭 {r["drawdown_pct"]:.1f}%"}}')
    if vix >= 30:
        noti_items.append(("warn", f"VIX {vix:.1f} — 공포 구간, 분할매수 기회"))
        noti_js_arr.append(f'{{"type":"warn","ticker":"MACRO","msg":"VIX {vix:.1f} 공포구간"}}')
    if not noti_items:
        noti_items.append(("info", "현재 특별한 매수 시그널이 없습니다. 그리드 레벨 도달 시 알려드릴게요."))

    noti_html = ""
    for ntype, text in noti_items[:6]:
        noti_html += f'<div class="noti-alert"><div class="na-dot {ntype}"></div><div class="na-text">{text}</div></div>'
    noti_js_data = "[" + ",".join(noti_js_arr) + "]"

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>우당탕탕 딩쵱 하우스 마련 대작전 - {now.strftime('%Y-%m-%d')}</title>
<link rel="manifest" href="./manifest.json">
<meta name="theme-color" content="#3182f6">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="딩쵱 대작전">
<link rel="apple-touch-icon" href="./icons/icon-192.png">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;background:#f2f4f6;color:#191f28;min-height:100vh;-webkit-font-smoothing:antialiased;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}}
.container{{max-width:680px;margin:0 auto;padding:0 16px 40px}}
.header{{padding:28px 20px 24px;text-align:center;background:linear-gradient(135deg,#3182f6 0%,#1b64da 100%);border-radius:0 0 24px 24px;margin:0 -16px 16px;position:relative;overflow:hidden}}
.header::before{{content:'';position:absolute;top:-40px;right:-30px;width:120px;height:120px;background:rgba(255,255,255,0.08);border-radius:50%}}
.header::after{{content:'';position:absolute;bottom:-20px;left:-20px;width:80px;height:80px;background:rgba(255,255,255,0.05);border-radius:50%}}
.header-icon{{width:56px;height:56px;border-radius:16px;margin:0 auto 12px;background:#fff;box-shadow:0 4px 12px rgba(0,0,0,0.15);display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative;z-index:1}}
.header-icon img{{width:100%;height:100%;object-fit:cover;border-radius:14px}}
.header h1{{font-size:20px;font-weight:700;color:#fff;letter-spacing:-0.5px;position:relative;z-index:1}}
.header .sub{{color:rgba(255,255,255,0.8);font-size:13px;margin-top:4px;font-weight:400;position:relative;z-index:1}}
.header .date{{display:inline-block;background:rgba(255,255,255,0.15);color:#fff;font-size:11px;font-weight:500;margin-top:10px;padding:4px 12px;border-radius:20px;backdrop-filter:blur(4px);position:relative;z-index:1}}
.header .market-pulse{{display:flex;justify-content:center;gap:12px;margin-top:12px;position:relative;z-index:1}}
.header .pulse-item{{display:flex;align-items:center;gap:4px;font-size:11px;color:rgba(255,255,255,0.9)}}
.header .pulse-dot{{width:6px;height:6px;border-radius:50%;animation:pulse 2s infinite}}
.pulse-dot.green{{background:#4ade80}}
.pulse-dot.yellow{{background:#fbbf24}}
.pulse-dot.red{{background:#f87171}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.4}}}}
.section{{background:#fff;border-radius:16px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}}
.section-title{{font-size:15px;font-weight:700;color:#191f28;margin-bottom:14px;letter-spacing:-0.3px}}
.macro-chips{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}}
.macro-chip{{background:#f2f4f6;border-radius:20px;padding:6px 14px;font-size:12px;color:#4e5968;display:flex;align-items:center;gap:4px}}
.macro-chip .val{{font-weight:700;color:#191f28}}
.regime-badge{{display:inline-flex;align-items:center;gap:4px;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:700;color:{rc};background:{rbg}}}
.macro-desc{{font-size:13px;color:#6b7684;line-height:1.6;margin-top:8px}}
.stats-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-top:1px solid #f2f4f6}}
.stat{{text-align:center;padding:16px 8px;border-right:1px solid #f2f4f6}}
.stat:last-child{{border-right:none}}
.stat .sl{{font-size:11px;color:#8b95a1;font-weight:400}}
.stat .sv{{font-size:20px;font-weight:700;color:#191f28;margin-top:2px}}
.stat .sv.blue{{color:#3182f6}}
.stat .sv.green{{color:#00c073}}
.tip-box{{background:#f8f9fa;border-radius:12px;padding:14px 16px;margin-top:12px}}
.tip-box p{{font-size:13px;color:#4e5968;line-height:1.6}}
.tip-box p+p{{margin-top:6px}}
.tip-box .warn{{color:#f04452;font-size:12px;margin-top:8px;padding:10px 12px;background:#fff5f5;border-radius:8px}}
.card{{background:#fff;border-radius:16px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);transition:transform 0.15s ease}}
.card:active{{transform:scale(0.98)}}
.card-head{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px}}
.card-head .left{{flex:1}}
.ticker{{font-size:18px;font-weight:700;color:#191f28;letter-spacing:-0.3px}}
.etf-sub{{font-size:12px;color:#8b95a1;margin-top:2px}}
.tags{{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500}}
.tag.lev{{background:#f3f0ff;color:#6b4eff}}
.tag.cat{{background:#e8f3ff;color:#3182f6}}
.tag.trend-up{{background:#e8faf0;color:#00a661}}
.tag.trend-dn{{background:#fff5f5;color:#f04452}}
.score-ring{{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative}}
.score-ring .num{{font-size:16px;font-weight:700}}
.score-ring svg{{position:absolute;top:0;left:0;transform:rotate(-90deg)}}
.verdict-bar{{border-radius:10px;padding:12px 14px;margin-bottom:14px}}
.verdict-bar .vd-title{{font-weight:700;font-size:14px;margin-bottom:2px}}
.verdict-bar .vd-detail{{font-size:12px;line-height:1.5;opacity:0.85}}
.price-area{{margin-bottom:14px}}
.price{{font-size:26px;font-weight:700;letter-spacing:-0.5px}}
.chg-pill{{display:inline-block;padding:3px 8px;border-radius:6px;font-size:13px;font-weight:500;margin-left:8px}}
.chg-pill.up{{background:#e8faf0;color:#00a661}}
.chg-pill.down{{background:#fff5f5;color:#f04452}}
.range-bar{{margin:10px 0 14px}}
.range-labels{{display:flex;justify-content:space-between;font-size:11px;color:#8b95a1;margin-bottom:4px}}
.range-track{{height:6px;background:#f2f4f6;border-radius:3px;position:relative;overflow:hidden}}
.range-fill{{height:100%;border-radius:3px;transition:width 0.5s}}
.range-dot{{position:absolute;top:-3px;width:12px;height:12px;border-radius:50%;background:#fff;border:2px solid #3182f6;transform:translateX(-50%);box-shadow:0 1px 3px rgba(0,0,0,0.15)}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-radius:12px;overflow:hidden;border:1px solid #f2f4f6;margin-bottom:14px}}
.metric{{padding:10px 4px;text-align:center;border-right:1px solid #f2f4f6;cursor:pointer;transition:background 0.15s}}
.metric:last-child{{border-right:none}}
.metric:active{{background:#f8f9fa}}
.metric.hi{{background:#e8faf0}}
.metric.warn{{background:#fff5f5}}
.ml{{font-size:11px;color:#8b95a1;font-weight:400}}
.mv{{font-size:14px;font-weight:700;color:#191f28;margin-top:1px}}
.metric.hi .mv{{color:#00a661}}
.metric.warn .mv{{color:#f04452}}
.buy-plan{{background:#f8f9fa;border-radius:12px;padding:14px;margin-bottom:10px}}
.buy-plan .bp-title{{font-size:13px;font-weight:700;color:#191f28;margin-bottom:4px}}
.buy-plan .bp-sub{{font-size:11px;color:#3182f6;margin-bottom:10px}}
.buy-plan table{{width:100%;font-size:12px;border-collapse:collapse}}
.buy-plan th{{text-align:left;color:#8b95a1;padding:4px;font-weight:500;font-size:11px;border-bottom:1px solid #e5e8eb}}
.buy-plan td{{padding:6px 4px;border-bottom:1px solid #f2f4f6;color:#191f28}}
.buy-plan tr.next-row{{background:#e8f3ff}}
.buy-plan tr.next-row td{{color:#3182f6;font-weight:700}}
.buy-plan .more{{text-align:center;color:#8b95a1;font-size:12px;padding:6px 0}}
.budget-bar{{display:flex;gap:4px;margin-top:8px;border-radius:8px;overflow:hidden;height:28px;font-size:11px;font-weight:500}}
.budget-bar .seg{{display:flex;align-items:center;justify-content:center}}
.budget-bar .seg.active{{background:#3182f6;color:#fff}}
.budget-bar .seg.reserve{{background:#e5e8eb;color:#4e5968}}
.info-row{{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}}
.info-chip{{background:#f2f4f6;border-radius:6px;padding:4px 10px;font-size:11px;color:#4e5968}}
.info-chip.danger{{background:#fff5f5;color:#f04452}}
.details{{font-size:11px;color:#b0b8c1;padding-top:10px;margin-top:10px;border-top:1px solid #f2f4f6;letter-spacing:-0.2px}}
.strategy-box{{background:#fff;border-radius:16px;padding:20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}}
.strategy-box h3{{font-size:15px;font-weight:700;margin-bottom:12px}}
.strat-item{{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f2f4f6;font-size:13px}}
.strat-item:last-child{{border-bottom:none}}
.strat-item .emoji{{font-size:16px;flex-shrink:0;width:24px}}
.strat-item .desc{{color:#4e5968;line-height:1.5}}
.strat-item .desc b{{color:#191f28}}
.strat-tips{{margin-top:12px;padding:12px;background:#f8f9fa;border-radius:10px;font-size:12px;color:#6b7684;line-height:1.6}}
.strat-tips .warn{{color:#f04452;margin-top:6px;padding:8px 10px;background:#fff5f5;border-radius:6px;font-size:11px}}
.footer{{text-align:center;padding:24px 0;font-size:12px;color:#b0b8c1}}
.footer a{{color:#3182f6;text-decoration:none;font-weight:500}}
.overlay{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:9999;backdrop-filter:blur(2px)}}
.overlay.show{{display:block}}
.popup{{display:none;position:fixed;bottom:0;left:0;right:0;background:#fff;border-radius:20px 20px 0 0;padding:24px 20px 32px;max-height:70vh;overflow-y:auto;z-index:10000;box-shadow:0 -4px 20px rgba(0,0,0,0.1)}}
.popup.show{{display:block}}
.popup .handle{{width:36px;height:4px;background:#e5e8eb;border-radius:2px;margin:0 auto 16px}}
.popup h3{{font-size:16px;font-weight:700;color:#191f28;margin-bottom:16px}}
.popup .close{{position:absolute;top:16px;right:16px;background:#f2f4f6;color:#6b7684;border:none;border-radius:50%;width:32px;height:32px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center}}
.popup ul{{list-style:none}}
.popup li{{padding:6px 0;font-size:13px;color:#4e5968;line-height:1.5}}
.popup .sec{{font-weight:700;color:#191f28;background:#f2f4f6;padding:8px 12px;margin:10px 0 6px;border-radius:8px;font-size:13px}}
.noti-bar{{background:#fff;border-radius:16px;padding:14px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);display:flex;align-items:center;justify-content:space-between}}
.noti-bar .noti-left{{display:flex;align-items:center;gap:10px}}
.noti-bar .noti-icon{{width:36px;height:36px;border-radius:10px;background:#e8f3ff;display:flex;align-items:center;justify-content:center;font-size:18px}}
.noti-bar .noti-text{{font-size:13px;color:#4e5968}}
.noti-bar .noti-text b{{color:#191f28}}
.noti-toggle{{position:relative;width:48px;height:28px;border-radius:14px;border:none;cursor:pointer;transition:background 0.2s;flex-shrink:0}}
.noti-toggle.on{{background:#3182f6}}
.noti-toggle.off{{background:#e5e8eb}}
.noti-toggle::after{{content:'';position:absolute;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,0.15);transition:left 0.2s}}
.noti-toggle.off::after{{left:3px}}
.noti-toggle.on::after{{left:23px}}
.noti-status{{font-size:11px;color:#8b95a1;margin-top:4px}}
.noti-alert-list{{margin-top:10px;display:none}}
.noti-alert-list.show{{display:block}}
.noti-alert{{display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid #f2f4f6;font-size:12px}}
.noti-alert:last-child{{border-bottom:none}}
.noti-alert .na-dot{{width:6px;height:6px;border-radius:50%;margin-top:5px;flex-shrink:0}}
.noti-alert .na-dot.buy{{background:#00c073}}
.noti-alert .na-dot.warn{{background:#ff9500}}
.noti-alert .na-dot.info{{background:#3182f6}}
.noti-alert .na-text{{color:#4e5968;line-height:1.5}}
.noti-alert .na-text b{{color:#191f28}}
@media(max-width:600px){{
.header{{margin:0 -12px 14px;padding:24px 16px 20px}}
.header h1{{font-size:17px}}
.header-icon{{width:48px;height:48px;border-radius:14px;margin-bottom:10px}}
.header .market-pulse{{gap:8px;flex-wrap:wrap}}
.header .pulse-item{{font-size:10px}}
.noti-bar{{padding:12px 14px;border-radius:14px}}
.noti-bar .noti-icon{{width:32px;height:32px;border-radius:8px;font-size:16px}}
.noti-bar .noti-text{{font-size:12px}}
.noti-toggle{{width:44px;height:26px}}
.noti-toggle::after{{width:20px;height:20px}}
.noti-toggle.on::after{{left:21px}}
.stats-row{{grid-template-columns:repeat(2,1fr)}}
.stat:nth-child(2){{border-right:none}}
.stat{{padding:12px 6px}}
.stat .sv{{font-size:17px}}
.metrics{{grid-template-columns:repeat(2,1fr)}}
.metric:nth-child(2){{border-right:none}}
.metric:nth-child(3),.metric:nth-child(4){{border-top:1px solid #f2f4f6}}
.container{{padding:0 12px 32px}}
.price{{font-size:22px}}
.card{{padding:16px;border-radius:14px}}
.card-head .left .ticker{{font-size:16px}}
.score-ring{{width:46px;height:46px}}
.score-ring .num{{font-size:14px}}
.buy-plan table{{font-size:11px}}
.buy-plan th{{font-size:10px}}
.buy-plan td{{padding:5px 3px}}
.range-labels{{font-size:10px}}
.macro-chips{{gap:6px}}
.macro-chip{{padding:5px 10px;font-size:11px}}
.strategy-box{{padding:16px}}
.strat-item{{font-size:12px}}
.popup{{padding:20px 16px 28px;max-height:75vh}}
}}
</style></head><body>
<div class="container">
<div class="header">
<div class="header-icon"><img src="./icons/icon-192.png" alt="딩쵱"></div>
<h1>우당탕탕 딩쵱 하우스 마련 대작전</h1>
<div class="sub">무한매수법 그리드 전략</div>
<div class="date">{now.strftime('%Y-%m-%d %H:%M')} KST</div>
<div class="market-pulse">
<div class="pulse-item"><div class="pulse-dot {"green" if regime in ("BULL_STRONG","BULL") else "yellow" if regime=="SIDEWAYS" else "red"}"></div>{regime_kr}</div>
<div class="pulse-item">VIX {vix:.1f}</div>
<div class="pulse-item">{buy_count}종목 매수 추천</div>
</div>
</div>

<div class="noti-bar" id="notiBar">
<div class="noti-left">
<div class="noti-icon">🔔</div>
<div>
<div class="noti-text"><b>매수 알림</b> {len(noti_items)}건</div>
<div class="noti-status" id="notiStatus">알림 허용 시 시그널을 푸시로 받아요</div>
</div>
</div>
<button class="noti-toggle off" id="notiToggle" onclick="toggleNoti()"></button>
</div>
<div class="noti-alert-list" id="notiList">
{noti_html}
</div>

<div class="section">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
<span class="regime-badge">{remoji} {regime_kr}</span>
</div>
<div class="macro-chips">
<div class="macro-chip">VIX <span class="val">{vix:.1f}</span></div>
<div class="macro-chip">금리 <span class="val">{rate:.2f}%</span></div>
<div class="macro-chip">S&P500 <span class="val">{sp500_1m:+.1f}%</span></div>
<div class="macro-chip">매크로 <span class="val">{macro_pct:.0%}</span></div>
</div>
<div class="macro-desc">{macro_desc}</div>
</div>

<div class="section">
<div class="stats-row">
<div class="stat"><div class="sl">분석 ETF</div><div class="sv">{total}</div></div>
<div class="stat"><div class="sl">매수 추천</div><div class="sv green">{buy_count}</div></div>
<div class="stat"><div class="sl">평균 점수</div><div class="sv">{avg_score:.0f}</div></div>
<div class="stat"><div class="sl">최고 점수</div><div class="sv blue">{best['ticker'] if best else '-'} {best['score'] if best else 0}</div></div>
</div>
</div>

<div class="section">
<div class="section-title">이 페이지 보는 법</div>
<div class="tip-box">
<p>각 ETF의 <b>점수</b>가 높을수록 지금 매수하기 좋은 타이밍이에요. <b>매수 계획표</b>에서 구체적인 매수 가격과 수량을 확인하세요.</p>
<p>투자비율 <b>{allocation*100:.0f}%</b> / 예비금 <b>{(1-allocation)*100:.0f}%</b> ({regime_kr}) · 무한매수법: 매수만, 익절 없음</p>
<div class="warn">손절 기준({STOP_LOSS_PCT:.0f}%)에 도달하면 추가 매수를 중단하고 포지션을 재검토하세요.</div>
</div>
</div>

"""

    for i, r in enumerate(results):
        chg_cls = "up" if r["change_pct"] >= 0 else "down"
        sign = "+" if r["change_pct"] >= 0 else ""
        vc, vbg, vborder = verdict_color(r["score"])

        # 추세 태그
        trend_tag = ""
        if r["trend_aligned"]:
            trend_tag = '<span class="tag trend-up">정배열</span>'
        elif r["price"] < r["sma200"]:
            trend_tag = '<span class="tag trend-dn">하락추세</span>'

        # 메트릭 하이라이트
        rsi_cls = "hi" if r["rsi"] < 35 else ("warn" if r["rsi"] > 65 else "")
        dd_cls = "hi" if r["drawdown_pct"] <= -15 else ""
        mom_cls = "hi" if r["mom_1m"] < -3 else ("warn" if r["mom_1m"] > 8 else "")
        sma_cls = "hi" if r["trend_aligned"] else ("warn" if r["price"] < r["sma200"] else "")

        # 스코어 링 SVG (토스 스타일 원형 프로그레스)
        score_pct = min(r["score"], 100)
        circumference = 2 * 3.14159 * 22
        stroke_offset = circumference * (1 - score_pct / 100)

        # 매수 계획표
        buy_table = ""
        if r["grid_levels"]:
            rows = ""
            shown = 0
            for gl in r["grid_levels"]:
                if shown >= 6:
                    break
                is_next = r["next_buy"] and gl.level_number == r["next_buy"].level_number
                tr_cls = ' class="next-row"' if is_next else ""
                marker = " ←" if is_next else ""
                rows += f'<tr{tr_cls}><td>L{gl.level_number}</td><td>${gl.target_price:.2f}{marker}</td><td>-{gl.drop_pct:.1f}%</td><td>{gl.quantity}주</td><td>${gl.budget_allocation:,.0f}</td></tr>'
                shown += 1

            remaining = len(r["grid_levels"]) - shown
            more = f'<div class="more">+{remaining}개 레벨</div>' if remaining > 0 else ""

            alloc = r.get("allocation", 0.55)
            buy_table = f"""<div class="buy-plan">
<div class="bp-title">무한매수 계획표</div>
<div class="bp-sub">투자 ${r['grid_budget']:,.0f} + 예비금 ${r['reserve_budget']:,.0f} · 레벨 도달 시 매수 → 장기 보유</div>
<table>
<tr><th>레벨</th><th>매수가</th><th>하락폭</th><th>수량</th><th>금액</th></tr>
{rows}
</table>
{more}
<div class="budget-bar">
<div class="seg active" style="flex:{alloc}">투자 {alloc*100:.0f}%</div>
<div class="seg reserve" style="flex:{1-alloc}">예비금 {(1-alloc)*100:.0f}%</div>
</div>
</div>"""

        # 52주 위치 바
        bar_color = "#00c073" if r["pos_52w"] < 30 else ("#ff9500" if r["pos_52w"] < 70 else "#f04452")
        pos_bar = f"""<div class="range-bar">
<div class="range-labels"><span>${r['low_52w']:.2f}</span><span>52주</span><span>${r['high_52w']:.2f}</span></div>
<div class="range-track"><div class="range-fill" style="width:{r['pos_52w']:.0f}%;background:{bar_color}"></div><div class="range-dot" style="left:{r['pos_52w']:.0f}%"></div></div>
</div>"""

        html += f"""<div class="card">
<div class="card-head">
<div class="left">
<div class="ticker">{r['ticker']}</div>
<div class="etf-sub">{r['name']} · 기초: {r['underlying']}</div>
<div class="tags">
<span class="tag lev">{r['leverage']}x</span>
<span class="tag cat">{r['category']}</span>
{trend_tag}
</div>
</div>
<div class="score-ring">
<svg width="52" height="52"><circle cx="26" cy="26" r="22" fill="none" stroke="#f2f4f6" stroke-width="4"/><circle cx="26" cy="26" r="22" fill="none" stroke="{vborder}" stroke-width="4" stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{stroke_offset:.1f}" stroke-linecap="round"/></svg>
<span class="num" style="color:{vc}">{r['score']}</span>
</div>
</div>

<div class="verdict-bar" style="background:{vbg}">
<div class="vd-title" style="color:{vc}">{signal_emoji(r['score'])} {r['verdict']}</div>
<div class="vd-detail" style="color:{vc}">{r['verdict_detail']}</div>
</div>

<div class="price-area">
<span class="price">${r['price']:.2f}</span>
<span class="chg-pill {chg_cls}">{sign}{r['change_pct']:.2f}%</span>
</div>

{pos_bar}

<div class="metrics">
<div class="metric {rsi_cls}" onclick="showInfo('rsi')"><div class="ml">RSI</div><div class="mv">{r['rsi']:.0f}</div></div>
<div class="metric {dd_cls}" onclick="showInfo('dd')"><div class="ml">ATH 낙폭</div><div class="mv">{r['drawdown_pct']:.1f}%</div></div>
<div class="metric {mom_cls}" onclick="showInfo('mom')"><div class="ml">1개월</div><div class="mv">{r['mom_1m']:+.1f}%</div></div>
<div class="metric {sma_cls}" onclick="showInfo('sma')"><div class="ml">추세</div><div class="mv">{'정배열' if r['trend_aligned'] else '역배열'}</div></div>
</div>

{buy_table}

<div class="info-row">
<span class="info-chip">무한매수 · 장기 보유</span>
<span class="info-chip danger">손절 ${r['stop_loss_price']:.2f} ({STOP_LOSS_PCT:.0f}%)</span>
</div>

<div class="details">
ATH ${r['ath']:.2f} · SMA20 ${r['sma20']:.2f} · SMA50 ${r['sma50']:.2f} · SMA200 ${r['sma200']:.2f} · 3M {r['mom_3m']:+.1f}% · Vol {r['vol_annual']:.0f}%
</div>
</div>
"""

    html += f"""
<div class="strategy-box">
<h3>무한매수법 전략 v3</h3>
<div class="strat-item"><span class="emoji">🚀</span><div class="desc"><b>강한 상승장</b> (투자 75%): 시드매수 30% 진입 → 풀백 시 그리드 추가매수 → 장기 보유</div></div>
<div class="strat-item"><span class="emoji">📈</span><div class="desc"><b>상승장</b> (투자 70%): 시드매수 30% → 눌림목 그리드 매수 → 장기 보유</div></div>
<div class="strat-item"><span class="emoji">➡️</span><div class="desc"><b>횡보장</b> (투자 55%): 그리드 레벨 도달 시 매수 + 유휴 현금 DCA</div></div>
<div class="strat-item"><span class="emoji">📉</span><div class="desc"><b>하락장</b> (투자 45%): 예비금 55% 유지 + 하위 레벨 위주 매수 → 장기 보유</div></div>
<div class="strat-item"><span class="emoji">🔥</span><div class="desc"><b>위기</b> (투자 40%): 예비금 60% 유지, 극단적 저점 소량 매수 → 장기 보유</div></div>
<div class="strat-tips">
그리드 상단 15% 이탈 시 자동 리밸런싱 · 유휴 현금 월 1회 DCA 자동 매수<br>
횡보장에서 3x ETF(TQQQ/SOXL)는 디케이 주의 → 2x(QLD/SSO)가 안전
<div class="warn">손절 기준 {STOP_LOSS_PCT:.0f}% 초과 손실 시 → 추가 매수 중단 → 포지션 재평가</div>
</div>
</div>

<div class="footer">
<p>본 리포트는 교육/참고 목적이며 투자 조언이 아닙니다.</p>
<p style="margin-top:4px"><a href="https://github.com/redchoeng/etf_guide">GitHub</a> · {now.strftime('%Y-%m-%d %H:%M')} KST</p>
</div>
</div>

<div class="overlay" id="ov" onclick="hideInfo()"></div>
<div class="popup" id="pop"><div class="handle"></div><button class="close" onclick="hideInfo()">✕</button><h3 id="popT"></h3><ul id="popC"></ul></div>
<script>
const info={{
rsi:{{t:'RSI (상대강도지수)',c:[
{{s:'RSI란?',i:['주가의 과매수/과매도를 0~100으로 표시','14일간 상승폭 vs 하락폭 비율']}},
{{s:'해석 기준',i:['🟢 30 미만: 과매도 (매수 기회!)','🟡 30~70: 중립','🟠 70 이상: 과매수 (조심!)']}},
{{s:'활용법',i:['RSI 30 이하에서 분할매수 시작','RSI 70 이상에서 추가 매수 보류 (보유분 장기 보유)']}}
]}},
dd:{{t:'ATH 대비 낙폭',c:[
{{s:'ATH 낙폭이란?',i:['역대 최고가(ATH) 대비 현재가의 하락률','낙폭이 클수록 싸게 살 수 있는 기회']}},
{{s:'레버리지 ETF 낙폭 기준',i:['🟢 -20% 이상: 매수 적극 고려','🟡 -10%~-20%: 관심 구간','🟠 -5%~-10%: 관망','🔴 -5% 미만: 고점 영역']}},
{{s:'주의사항',i:['레버리지 ETF는 기초지수보다 낙폭이 2~3배 깊음','TQQQ는 QQQ -30% 때 -60% 이상 빠질 수 있음']}}
]}},
mom:{{t:'모멘텀 (1개월 수익률)',c:[
{{s:'모멘텀이란?',i:['최근 1개월간 가격 변동률','상승장에서 풀백(조정)을 포착하는 핵심 지표']}},
{{s:'상승장 활용',i:['🟢 -2%~-5%: 건강한 풀백 (매수 타이밍)','🟡 0% 부근: 안정적 상승','🟠 +8% 이상: 단기 과열 주의']}},
{{s:'하락장 활용',i:['🟢 +3% 이상: 반등 시작 시그널','🟡 0% 부근: 바닥 다지기','🔴 -10% 이하: 극단적 하락 (역발상 매수)']}}
]}},
sma:{{t:'추세 (이동평균선 배열)',c:[
{{s:'정배열이란?',i:['SMA20 > SMA50 > SMA200 순서','건강한 상승 추세를 의미함']}},
{{s:'역배열이란?',i:['SMA200 > SMA50 > SMA20 순서','하락 추세를 의미 → 그리드 매수 기회']}},
{{s:'상승장 매수법',i:['🟢 정배열 + SMA20 지지: 추세 매수 최적','🟢 정배열 + 풀백: 가장 좋은 매수 타이밍','🟡 SMA50 이탈 시: 추세 약화 주의']}}
]}}
}};
function showInfo(k){{const d=info[k];document.getElementById('popT').textContent=d.t;let h='';d.c.forEach(s=>{{h+='<li class="sec">'+s.s+'</li>';s.i.forEach(i=>{{h+='<li>'+i+'</li>'}});}});document.getElementById('popC').innerHTML=h;document.getElementById('ov').classList.add('show');document.getElementById('pop').classList.add('show');}}
function hideInfo(){{document.getElementById('ov').classList.remove('show');document.getElementById('pop').classList.remove('show');}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')hideInfo();}});

// === 알림 시스템 ===
const NOTI_KEY='ding_noti_enabled';
const NOTI_SENT_KEY='ding_noti_sent';
const alerts={noti_js_data};
let swReg=null;

// SW 등록
if('serviceWorker' in navigator){{
  navigator.serviceWorker.register('./sw.js').then(r=>{{swReg=r;}}).catch(()=>{{}});
}}

// 알림 토글 UI 초기화
function initNoti(){{
  const enabled=localStorage.getItem(NOTI_KEY)==='true';
  const toggle=document.getElementById('notiToggle');
  const status=document.getElementById('notiStatus');
  const list=document.getElementById('notiList');
  if(enabled && Notification.permission==='granted'){{
    toggle.className='noti-toggle on';
    status.textContent='알림이 켜져 있어요';
    list.classList.add('show');
    fireAlerts();
  }}else{{
    toggle.className='noti-toggle off';
    status.textContent='알림 허용 시 시그널을 푸시로 받아요';
    list.classList.remove('show');
  }}
}}

// 알림 토글
function toggleNoti(){{
  const toggle=document.getElementById('notiToggle');
  const isOn=toggle.classList.contains('on');
  if(isOn){{
    localStorage.setItem(NOTI_KEY,'false');
    initNoti();
  }}else{{
    if(!('Notification' in window)){{
      document.getElementById('notiStatus').textContent='이 브라우저는 알림을 지원하지 않아요';
      return;
    }}
    Notification.requestPermission().then(p=>{{
      if(p==='granted'){{
        localStorage.setItem(NOTI_KEY,'true');
        initNoti();
      }}else{{
        document.getElementById('notiStatus').textContent='알림이 차단되었어요. 브라우저 설정에서 허용해주세요';
      }}
    }});
  }}
}}

// 시그널 알림 발송
function fireAlerts(){{
  const today=new Date().toDateString();
  const sent=localStorage.getItem(NOTI_SENT_KEY);
  if(sent===today)return; // 하루 1회만

  if(alerts.length===0)return;
  localStorage.setItem(NOTI_SENT_KEY,today);

  // 가장 중요한 알림 1개는 즉시
  sendNoti('🔔 딩쵱 매수 시그널',alerts[0].msg,'ding-main');

  // 나머지는 30초 간격으로
  alerts.slice(1,4).forEach((a,i)=>{{
    setTimeout(()=>{{sendNoti('📊 '+a.ticker,a.msg,'ding-'+a.ticker);}}, (i+1)*30000);
  }});
}}

function sendNoti(title,body,tag){{
  if(swReg){{
    swReg.active?.postMessage({{type:'SHOW_NOTIFICATION',title,body,tag}});
  }}else{{
    new Notification(title,{{body,icon:'./icons/icon-192.png',tag}});
  }}
}}

// 알림바 클릭 시 목록 토글
document.getElementById('notiBar').addEventListener('click',e=>{{
  if(e.target.id==='notiToggle')return;
  document.getElementById('notiList').classList.toggle('show');
}});

initNoti();
</script>
</body></html>"""

    return html


def main():
    print("🏠 우당탕탕 딩쵱 하우스 마련 대작전 리포트 생성 시작...")
    now = datetime.now(KST)
    config = load_config()
    presets = load_presets()

    # 매크로 환경 분석
    print("  매크로 환경 분석 중...")
    macro_analyzer = MacroAnalyzer()
    macro = macro_analyzer.analyze()
    print(f"    시장: {macro['regime_kr']} | VIX: {macro['vix']:.1f} | 금리: {macro['rate_10y']:.2f}% | 매크로 점수: {macro['macro_score']:.0%}")

    results = []
    for ticker, preset in presets.get("presets", {}).items():
        print(f"  분석 중: {ticker}...")
        r = analyze_etf(ticker, preset, config, macro)
        if r:
            results.append(r)
            print(f"    ${r['price']:.2f} ({r['change_pct']:+.2f}%) | {r['score']}점 | {r['verdict']}")

    if not results:
        print("❌ 분석 결과 없음")
        return

    html = generate_html(results, macro, now)
    output_file = f"etf_report_{now.strftime('%Y%m%d')}.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 리포트 생성: {output_file} ({len(results)}개 ETF)")

    index_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url=./{output_file}">
    <title>우당탕탕 딩쵱 하우스 마련 대작전</title>
</head>
<body>
    <p>최신 리포트로 이동 중... <a href="./{output_file}">클릭</a></p>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    print("✅ index.html 업데이트")

    return results


if __name__ == "__main__":
    main()
