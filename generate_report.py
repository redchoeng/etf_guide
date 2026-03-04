#!/usr/bin/env python
"""
ETF 분할매수 가이드 HTML 리포트 생성기.

GitHub Actions에서 자동 실행되어 사용자용 HTML 리포트를 생성합니다.
stock-recommendations 2.0 스타일 디자인.
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

KST = timezone(timedelta(hours=9))


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_presets():
    preset_path = Path(__file__).parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def analyze_etf(ticker: str, preset: dict, config: dict) -> dict | None:
    """단일 ETF 종합 분석."""
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

        # 매수 점수 (100점 만점)
        score = calculate_score(rsi, drawdown_pct, current_price, sma20, sma50, sma200, vol_annual, strength)

        # 그리드 계산
        gc = GridCalculator(config.get("grid", {}))
        grid = gc.calculate_grid(
            reference_price=current_price,
            total_budget=preset.get("suggested_budget", 10000),
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

        # 판정 텍스트
        verdict, verdict_detail = get_verdict(score, overall, drawdown_pct, rsi, next_buy, current_price)

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
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pos_52w": pos_52w,
            "grid_levels": grid,
            "next_buy": next_buy,
            "suggested_budget": preset.get("suggested_budget", 10000),
            "verdict": verdict,
            "verdict_detail": verdict_detail,
        }
    except Exception as e:
        print(f"  {ticker} 분석 실패: {e}")
        return None


def calculate_score(rsi, drawdown_pct, price, sma20, sma50, sma200, vol, strength):
    """매수 매력도 점수 (100점 만점).

    - 가격 위치 (30점): 낙폭 깊을수록, 52주 저점 가까울수록 높음
    - 기술적 (25점): RSI 과매도, SMA 지지
    - 변동성 (15점): 변동성 낮을수록 안정적
    - 복합 시그널 (30점): signal_generator 복합 점수 반영
    """
    score = 0

    # 가격 위치 (30점) - 낙폭 깊을수록 매수 매력
    dd = abs(drawdown_pct)
    if dd >= 40:
        score += 30
    elif dd >= 30:
        score += 25
    elif dd >= 20:
        score += 20
    elif dd >= 10:
        score += 14
    elif dd >= 5:
        score += 8
    else:
        score += 3

    # 기술적 (25점)
    # RSI
    if rsi < 25:
        score += 12
    elif rsi < 30:
        score += 10
    elif rsi < 40:
        score += 7
    elif rsi < 50:
        score += 5
    elif rsi < 60:
        score += 3
    elif rsi < 70:
        score += 1

    # SMA 지지
    if price < sma200:
        score += 8  # 200일선 아래 = 깊은 할인
    elif price < sma50:
        score += 5
    elif price < sma20:
        score += 3
    else:
        score += 1  # 모든 이평선 위 = 과열 가능

    # 골든/데드크로스
    if sma20 > sma50:
        score += 5  # 골든크로스 (상승 추세)

    # 변동성 (15점) - 적당한 변동성이 좋음
    if vol <= 25:
        score += 15
    elif vol <= 35:
        score += 12
    elif vol <= 45:
        score += 8
    elif vol <= 55:
        score += 5
    else:
        score += 2

    # 복합 시그널 (30점)
    score += int(strength * 30)

    return min(score, 100)


def get_verdict(score, signal, drawdown_pct, rsi, next_buy, price):
    """사용자용 판정 + 상세 설명."""
    if score >= 75:
        verdict = "적극 매수 추천"
        if drawdown_pct <= -20:
            detail = f"ATH 대비 {drawdown_pct:.0f}% 하락, 역사적 저점 영역입니다. 그리드 매수를 적극 실행하세요."
        else:
            detail = "복합 시그널이 강한 매수를 가리킵니다. 분할매수 실행을 추천합니다."
    elif score >= 60:
        verdict = "매수 고려"
        if next_buy:
            gap = (next_buy.target_price - price) / price * 100
            detail = f"다음 그리드 레벨(${next_buy.target_price:.2f})까지 {abs(gap):.1f}% 남았습니다. 소량 선매수 또는 대기."
        else:
            detail = "시그널이 양호합니다. 소량 분할매수를 시작해볼 만합니다."
    elif score >= 40:
        verdict = "관망"
        detail = "뚜렷한 매수 시그널이 없습니다. 가격이 더 내려오면 진입하세요."
        if rsi > 60:
            detail = f"RSI {rsi:.0f}으로 과매수 영역 접근 중. 추가 매수보다 대기가 유리합니다."
    else:
        verdict = "대기"
        detail = "현재 고점 영역이거나 과매수 상태입니다. 조정을 기다리세요."
        if drawdown_pct > -3:
            detail = "ATH 근처입니다. 조정 시 매수 기회를 노리세요."

    return verdict, detail


def verdict_color(score):
    if score >= 75:
        return "#2E7D32", "#E8F5E9", "#4CAF50"  # 진한초록, 연초록배경, 보더
    elif score >= 60:
        return "#1565C0", "#E3F2FD", "#2196F3"
    elif score >= 40:
        return "#E65100", "#FFF3E0", "#FF9800"
    else:
        return "#C62828", "#FFEBEE", "#F44336"


def generate_html(results: list[dict], now: datetime) -> str:
    """2.0 스타일 사용자용 HTML 리포트."""
    total = len(results)
    buy_count = len([r for r in results if r["score"] >= 60])
    avg_score = sum(r["score"] for r in results) / total if total else 0
    best = max(results, key=lambda x: x["score"]) if results else None

    # 점수순 정렬
    results.sort(key=lambda x: x["score"], reverse=True)

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>레버리지 ETF 분할매수 가이드 - {now.strftime('%Y-%m-%d')}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans KR',sans-serif;background:linear-gradient(180deg,#87CEEB 0%,#98D8C8 30%,#F7DC6F 70%,#FADBD8 100%);background-attachment:fixed;padding:15px;color:#5D4E37;min-height:100vh}}
.cloud{{position:fixed;background:#fff;border-radius:50px;opacity:0.6;animation:float 35s infinite linear;z-index:0;pointer-events:none}}
.cloud::before,.cloud::after{{content:'';position:absolute;background:#fff;border-radius:50%}}
.c1{{width:80px;height:32px;top:6%;left:-80px}}.c1::before{{width:40px;height:40px;top:-20px;left:12px}}.c1::after{{width:28px;height:28px;top:-12px;left:44px}}
.c2{{width:100px;height:40px;top:18%;left:-100px;animation-delay:-12s}}.c2::before{{width:50px;height:50px;top:-25px;left:18px}}.c2::after{{width:35px;height:35px;top:-15px;left:58px}}
.c3{{width:70px;height:28px;top:32%;left:-70px;animation-delay:-22s}}.c3::before{{width:35px;height:35px;top:-18px;left:10px}}.c3::after{{width:24px;height:24px;top:-10px;left:38px}}
@keyframes float{{0%{{transform:translateX(0)}}100%{{transform:translateX(calc(100vw + 150px))}}}}
.container{{max-width:1200px;margin:0 auto;position:relative;z-index:10}}
.header{{background:#fff;border-radius:25px;padding:30px;margin-bottom:20px;box-shadow:0 6px 0 #2196F3;border:3px solid #5D4E37;text-align:center}}
.header h1{{font-size:1.6em;margin-bottom:5px;text-shadow:2px 2px 0 #E3F2FD}}
.header .sub{{color:#7B6B4F;font-size:0.9em}}
.header .date{{color:#2196F3;font-weight:700;margin-top:8px}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}}
.sum-card{{background:#FFF8DC;border-radius:15px;padding:14px;text-align:center;border:2px solid #5D4E37}}
.sum-card .label{{font-size:0.75em;color:#7B6B4F}}
.sum-card .value{{font-size:1.4em;font-weight:700;color:#FF6B35;margin-top:2px}}
.sum-card .value.buy{{color:#2E7D32}}
.sum-card .value.best{{color:#2196F3}}
.guide-box{{background:#fff;border-radius:18px;padding:18px;border:3px solid #5D4E37;box-shadow:0 4px 0 #E8A838;margin-bottom:20px}}
.guide-box h3{{color:#5D4E37;font-size:1em;margin-bottom:8px}}
.guide-box p{{font-size:0.85em;color:#7B6B4F;line-height:1.5}}
.guide-box .tip{{background:#FFF8DC;border-radius:10px;padding:10px;margin-top:8px;font-size:0.8em;border:1px dashed #C4A35A}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:15px;margin-bottom:20px}}
.card{{background:#fff;border-radius:18px;padding:18px;border:3px solid #5D4E37;box-shadow:0 5px 0 #E8A838;transition:transform 0.2s}}
.card:hover{{transform:translateY(-3px)}}
.card.top{{box-shadow:0 5px 0 #4CAF50;border-color:#2E7D32}}
.card-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:10px;border-bottom:2px dashed #C4A35A}}
.ticker{{font-size:1.3em;font-weight:700;color:#5D4E37}}
.etf-sub{{font-size:0.72em;color:#7B6B4F;margin-top:1px}}
.badge{{display:inline-block;padding:2px 7px;border-radius:8px;font-size:0.68em;font-weight:700;margin-left:4px}}
.badge.lev{{background:#7C4DFF;color:#fff}}
.badge.cat{{background:#2196F3;color:#fff}}
.score-circle{{width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.1em;border:3px solid #5D4E37;flex-shrink:0}}
.verdict-box{{border-radius:12px;padding:12px;margin-bottom:12px}}
.verdict-box .vd-title{{font-weight:700;font-size:0.95em;margin-bottom:4px}}
.verdict-box .vd-detail{{font-size:0.8em;line-height:1.4}}
.price-row{{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}}
.price{{font-size:1.2em;font-weight:700}}
.chg{{padding:3px 8px;border-radius:8px;font-size:0.85em}}
.up{{background:#E8F5E9;color:#2E7D32}}
.down{{background:#FFEBEE;color:#C62828}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px}}
.metric{{background:#FFF8DC;padding:8px 4px;border-radius:10px;text-align:center;border:2px solid #C4A35A;cursor:pointer;transition:all 0.2s}}
.metric:hover{{transform:scale(1.05);box-shadow:0 3px 8px rgba(0,0,0,0.12)}}
.metric.hi{{background:linear-gradient(135deg,#4CAF50,#45A049);border-color:#388E3C}}
.metric.hi .ml,.metric.hi .mv{{color:#fff}}
.metric.warn{{background:linear-gradient(135deg,#FF9800,#F57C00);border-color:#E65100}}
.metric.warn .ml,.metric.warn .mv{{color:#fff}}
.ml{{font-size:0.62em;color:#7B6B4F}}
.mv{{font-size:0.85em;font-weight:700;color:#5D4E37}}
.buy-plan{{background:#E8F5E9;border-radius:12px;padding:12px;margin-top:8px;border:2px solid #4CAF50}}
.buy-plan .bp-title{{font-size:0.8em;font-weight:700;color:#2E7D32;margin-bottom:6px}}
.buy-plan table{{width:100%;font-size:0.78em;border-collapse:collapse}}
.buy-plan th{{text-align:left;color:#2E7D32;padding:3px 4px;border-bottom:1px solid #A5D6A7;font-weight:700}}
.buy-plan td{{padding:4px;border-bottom:1px solid #C8E6C9}}
.buy-plan tr.next-row{{background:#C8E6C9;font-weight:700;border-radius:6px}}
.buy-plan tr.next-row td{{color:#1B5E20}}
.buy-plan .more{{text-align:center;color:#7B6B4F;font-size:0.75em;padding:4px}}
.pos-bar{{height:8px;background:#E0E0E0;border-radius:4px;margin:4px 0;overflow:hidden}}
.pos-bar .fill{{height:100%;border-radius:4px;transition:width 0.5s}}
.details{{font-size:0.7em;color:#9E9E9E;padding-top:6px;margin-top:6px;border-top:1px dashed #C4A35A}}
.overlay{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999}}
.overlay.show{{display:block}}
.popup{{display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;border-radius:20px;padding:22px;max-width:420px;width:92%;max-height:80vh;overflow-y:auto;z-index:10000;border:4px solid #5D4E37;box-shadow:0 8px 0 #C4A35A}}
.popup.show{{display:block}}
.popup h3{{color:#5D4E37;border-bottom:3px solid #2196F3;padding-bottom:10px;margin-bottom:15px}}
.popup .close{{position:absolute;top:10px;right:15px;background:#E53935;color:#fff;border:none;border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:1.2em}}
.popup ul{{list-style:none}}
.popup li{{padding:5px 0;border-bottom:1px dashed #C4A35A;font-size:0.88em}}
.popup .sec{{font-weight:700;color:#2196F3;background:#E3F2FD;padding:8px;margin:8px -10px;border-radius:8px}}
.footer{{background:#fff;border-radius:18px;padding:20px;text-align:center;border:3px solid #5D4E37;margin-top:20px}}
.footer p{{font-size:0.82em;color:#7B6B4F;margin:3px 0}}
.footer a{{color:#2196F3;text-decoration:none;font-weight:700}}
@media(max-width:600px){{.summary{{grid-template-columns:repeat(2,1fr)}}.metrics{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}.header h1{{font-size:1.3em}}}}
</style></head><body>
<div class="cloud c1"></div><div class="cloud c2"></div><div class="cloud c3"></div>
<div class="container">
<div class="header">
<div style="font-size:2.2em">📊</div>
<h1>레버리지 ETF 분할매수 가이드</h1>
<div class="sub">그리드 전략 기반 | 언제 · 얼마에 · 몇 주 사야 하는지</div>
<div class="date">🕐 {now.strftime('%Y-%m-%d %H:%M')} KST 업데이트</div>
</div>

<div class="summary">
<div class="sum-card"><div class="label">분석 ETF</div><div class="value">{total}개</div></div>
<div class="sum-card"><div class="label">매수 추천</div><div class="value buy">{buy_count}개</div></div>
<div class="sum-card"><div class="label">평균 점수</div><div class="value">{avg_score:.0f}점</div></div>
<div class="sum-card"><div class="label">최고 점수</div><div class="value best">{best['ticker'] if best else '-'} {best['score'] if best else 0}점</div></div>
</div>

<div class="guide-box">
<h3>💡 이 페이지 보는 법</h3>
<p>각 ETF 카드의 <b>점수</b>가 높을수록 지금 매수하기 좋은 타이밍입니다.<br>
<b>매수 계획표</b>에서 "얼마에 몇 주 사야 하는지" 구체적 금액을 확인하세요.<br>
가격이 내려갈수록 더 많이 사는 <b>피라미딩(분할매수)</b> 전략입니다.</p>
<div class="tip">💰 예산 $10,000 기준 | 🎯 목표 수익률 +10% | 📐 하락할수록 비중↑</div>
</div>

<div class="grid">
"""

    for i, r in enumerate(results):
        is_top = r["score"] >= 60
        card_cls = "card top" if is_top else "card"

        chg_cls = "up" if r["change_pct"] >= 0 else "down"
        sign = "+" if r["change_pct"] >= 0 else ""

        vc, vbg, vborder = verdict_color(r["score"])

        # 메트릭 하이라이트
        rsi_cls = "hi" if r["rsi"] < 35 else ("warn" if r["rsi"] > 65 else "")
        dd_cls = "hi" if r["drawdown_pct"] <= -15 else ""
        vol_cls = "warn" if r["vol_annual"] > 50 else ""
        sma_cls = "hi" if r["price"] < r["sma50"] else ""

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
                marker = " 👈 다음" if is_next else ""
                drop = gl.drop_pct
                rows += f"""<tr{tr_cls}>
<td>L{gl.level_number}</td>
<td>${gl.target_price:.2f}{marker}</td>
<td>-{drop:.1f}%</td>
<td>{gl.quantity}주</td>
<td>${gl.budget_allocation:,.0f}</td>
</tr>"""
                shown += 1

            remaining = len(r["grid_levels"]) - shown
            more = f'<div class="more">+{remaining}개 레벨 더 있음</div>' if remaining > 0 else ""

            buy_table = f"""<div class="buy-plan">
<div class="bp-title">📋 매수 계획표 (예산 ${r['suggested_budget']:,})</div>
<table>
<tr><th>레벨</th><th>매수가</th><th>하락폭</th><th>수량</th><th>금액</th></tr>
{rows}
</table>
{more}
</div>"""

        # 52주 위치 바
        bar_color = "#4CAF50" if r["pos_52w"] < 30 else ("#FF9800" if r["pos_52w"] < 70 else "#F44336")
        pos_bar = f"""<div style="font-size:0.7em;color:#7B6B4F;margin-bottom:6px">52주 위치: 저점 ${r['low_52w']:.2f} ← <b>${r['price']:.2f}</b> → 고점 ${r['high_52w']:.2f}</div>
<div class="pos-bar"><div class="fill" style="width:{r['pos_52w']:.0f}%;background:{bar_color}"></div></div>"""

        html += f"""<div class="{card_cls}">
<div class="card-head">
<div>
<span class="ticker">{r['ticker']}</span>
<span class="badge lev">{r['leverage']}x 레버리지</span>
<span class="badge cat">{r['category']}</span>
<div class="etf-sub">{r['name']} (기초: {r['underlying']})</div>
</div>
<div class="score-circle" style="background:{vbg};color:{vc};border-color:{vborder}">{r['score']}점</div>
</div>

<div class="verdict-box" style="background:{vbg};border:2px solid {vborder}">
<div class="vd-title" style="color:{vc}">{signal_emoji(r['score'])} {r['verdict']}</div>
<div class="vd-detail" style="color:{vc}">{r['verdict_detail']}</div>
</div>

<div class="price-row">
<span class="price">${r['price']:.2f}</span>
<span class="chg {chg_cls}">{sign}{r['change_pct']:.2f}%</span>
</div>

{pos_bar}

<div class="metrics">
<div class="metric {rsi_cls}" onclick="showInfo('rsi')"><div class="ml">RSI</div><div class="mv">{r['rsi']:.0f}</div></div>
<div class="metric {dd_cls}" onclick="showInfo('dd')"><div class="ml">ATH 낙폭</div><div class="mv">{r['drawdown_pct']:.1f}%</div></div>
<div class="metric {vol_cls}" onclick="showInfo('vol')"><div class="ml">변동성</div><div class="mv">{r['vol_annual']:.0f}%</div></div>
<div class="metric {sma_cls}" onclick="showInfo('sma')"><div class="ml">SMA50</div><div class="mv">${r['sma50']:.2f}</div></div>
</div>

{buy_table}

<div class="details">
ATH ${r['ath']:.2f} | SMA20 ${r['sma20']:.2f} | SMA200 ${r['sma200']:.2f} | 복합강도 {r['strength']:.0%}
</div>
</div>
"""

    html += f"""</div>

<div class="guide-box">
<h3>📖 분할매수 전략 요약</h3>
<p>
<b>1단계</b>: 점수가 60점 이상인 ETF 중심으로 매수 시작<br>
<b>2단계</b>: 가격이 "다음 레벨"까지 내려오면 해당 수량만큼 추가 매수<br>
<b>3단계</b>: 평균단가 대비 +10% 수익 도달 시 전량 매도<br>
<b>4단계</b>: 매도 후 새 그리드로 재시작 (수익 재투자)
</p>
<div class="tip">⚠️ 레버리지 ETF는 장기 보유 시 디케이(감쇠)가 발생합니다. 반드시 분할매수 + 목표 수익 매도 전략을 지키세요.</div>
</div>

<div class="footer">
<p>⚠️ 본 리포트는 교육/참고 목적이며 투자 조언이 아닙니다.</p>
<p>레버리지 ETF는 높은 위험을 수반합니다. 투자 결정은 본인 책임입니다.</p>
<p style="margin-top:8px"><a href="https://github.com/redchoeng/etf_guide">GitHub</a> | 자동 생성 ({now.strftime('%Y-%m-%d %H:%M')} KST)</p>
</div>
</div>

<div class="overlay" id="ov" onclick="hideInfo()"></div>
<div class="popup" id="pop"><button class="close" onclick="hideInfo()">&times;</button><h3 id="popT"></h3><ul id="popC"></ul></div>
<script>
const info={{
rsi:{{t:'RSI (상대강도지수)',c:[
{{s:'RSI란?',i:['주가의 과매수/과매도를 0~100으로 표시','14일간 상승폭 vs 하락폭 비율']}},
{{s:'해석 기준',i:['🟢 30 미만: 과매도 (매수 기회!)','🟡 30~70: 중립','🟠 70 이상: 과매수 (조심!)']}},
{{s:'활용법',i:['RSI 30 이하에서 분할매수 시작','RSI 70 이상에서 수익 확정 고려']}}
]}},
dd:{{t:'ATH 대비 낙폭',c:[
{{s:'ATH 낙폭이란?',i:['역대 최고가(ATH) 대비 현재가의 하락률','낙폭이 클수록 싸게 살 수 있는 기회']}},
{{s:'레버리지 ETF 낙폭 기준',i:['🟢 -20% 이상: 매수 적극 고려','🟡 -10%~-20%: 관심 구간','🟠 -5%~-10%: 관망','🔴 -5% 미만: 고점 영역']}},
{{s:'주의사항',i:['레버리지 ETF는 기초지수보다 낙폭이 2~3배 깊음','TQQQ는 QQQ -30% 때 -60% 이상 빠질 수 있음']}}
]}},
vol:{{t:'연환산 변동성',c:[
{{s:'변동성이란?',i:['가격의 일별 변동폭을 연간으로 환산한 값','높을수록 가격 변동이 크고 위험함']}},
{{s:'레버리지 ETF 기준',i:['🟢 30% 이하: 안정적','🟡 30~50%: 보통','🟠 50% 이상: 매우 높음 (주의!)']}},
{{s:'왜 중요한가?',i:['변동성이 높으면 레버리지 디케이도 커짐','변동성 큰 시기에는 분할매수 간격을 넓게 설정']}}
]}},
sma:{{t:'이동평균선 (SMA)',c:[
{{s:'SMA란?',i:['N일간 종가 평균으로 추세를 판단','SMA20(단기), SMA50(중기), SMA200(장기)']}},
{{s:'매수 시그널',i:['🟢 현재가 < SMA50: 중기 저점 (매수 기회)','🟢 SMA20 > SMA50: 골든크로스 (상승 전환)','🔴 현재가 > 모든 SMA: 과열 가능성']}},
{{s:'활용법',i:['SMA200 아래 진입 시 가장 큰 할인','SMA50 부근에서 반등 확인 후 매수']}}
]}}
}};
function showInfo(k){{const d=info[k];document.getElementById('popT').textContent=d.t;let h='';d.c.forEach(s=>{{h+='<li class="sec">'+s.s+'</li>';s.i.forEach(i=>{{h+='<li>'+i+'</li>'}});}});document.getElementById('popC').innerHTML=h;document.getElementById('ov').classList.add('show');document.getElementById('pop').classList.add('show');}}
function hideInfo(){{document.getElementById('ov').classList.remove('show');document.getElementById('pop').classList.remove('show');}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')hideInfo();}});
</script>
</body></html>"""

    return html


def signal_emoji(score_or_signal):
    """점수 또는 시그널 기반 이모지."""
    if isinstance(score_or_signal, (int, float)):
        if score_or_signal >= 75:
            return "🟢"
        elif score_or_signal >= 60:
            return "🔵"
        elif score_or_signal >= 40:
            return "🟡"
        else:
            return "🟠"
    return {
        "STRONG_BUY": "🟢",
        "BUY": "🔵",
        "HOLD": "🟡",
        "WAIT": "🟠",
    }.get(score_or_signal, "⚪")


def main():
    print("📊 ETF 분할매수 가이드 리포트 생성 시작...")
    now = datetime.now(KST)
    config = load_config()
    presets = load_presets()

    results = []
    for ticker, preset in presets.get("presets", {}).items():
        print(f"  분석 중: {ticker}...")
        r = analyze_etf(ticker, preset, config)
        if r:
            results.append(r)
            print(f"    ${r['price']:.2f} ({r['change_pct']:+.2f}%) | {r['score']}점 | {r['verdict']}")

    if not results:
        print("❌ 분석 결과 없음")
        return

    html = generate_html(results, now)
    output_file = f"etf_report_{now.strftime('%Y%m%d')}.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 리포트 생성: {output_file} ({len(results)}개 ETF)")

    # index.html 리다이렉트
    index_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url=./{output_file}">
    <title>ETF 분할매수 가이드</title>
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
