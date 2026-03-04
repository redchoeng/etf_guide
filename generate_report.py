#!/usr/bin/env python
"""
ETF 분할매수 가이드 HTML 리포트 생성기.

GitHub Actions에서 자동 실행되어 HTML 리포트를 생성합니다.
stock-recommendations 스타일의 보기 좋은 리포트를 생성합니다.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

import yaml
import yfinance as yf
import pandas as pd
import numpy as np

from engine.data_fetcher import ETFDataFetcher
from engine.signal_generator import SignalGenerator
from engine.grid_calculator import GridCalculator
from engine.drawdown_analyzer import DrawdownAnalyzer

KST = timezone(timedelta(hours=9))
ET = timezone(timedelta(hours=-5))


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_presets():
    preset_path = Path(__file__).parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def analyze_etf(ticker: str, preset: dict, config: dict) -> dict | None:
    """단일 ETF 분석."""
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

        # 시그널 생성
        signals = signal_gen.generate_signals(df)
        overall = signals.get("overall_signal", "HOLD")
        strength = signals.get("signal_strength", 0)
        rsi = signals.get("rsi_14", 50)

        # 낙폭 계산
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

        # 그리드 계산 (현재가 기준)
        gc = GridCalculator(config.get("grid", {}))
        grid = gc.calculate_grid(
            reference_price=current_price,
            total_budget=preset.get("suggested_budget", 10000),
            num_levels=preset.get("suggested_levels", 10),
            spacing_pct=preset.get("suggested_spacing", 5.0),
            weighting_method="linear",
        )

        # 다음 매수 레벨
        next_buy = None
        for gl in grid:
            if gl.target_price < current_price:
                next_buy = gl
                break

        # 52주 범위
        high_52w = float(close.max())
        low_52w = float(close.min())

        # 기초지수 정보
        underlying = preset.get("underlying", "")
        leverage = preset.get("leverage", 2)

        return {
            "ticker": ticker,
            "name": preset.get("name", ticker),
            "underlying": underlying,
            "leverage": leverage,
            "category": preset.get("category", ""),
            "price": current_price,
            "change_pct": change_pct,
            "signal": overall,
            "strength": strength,
            "rsi": rsi,
            "drawdown_pct": drawdown_pct,
            "ath": ath,
            "vol_annual": vol_annual,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "grid_levels": grid,
            "next_buy": next_buy,
            "suggested_budget": preset.get("suggested_budget", 10000),
        }
    except Exception as e:
        print(f"  {ticker} 분석 실패: {e}")
        return None


def signal_kr(signal: str) -> str:
    return {
        "STRONG_BUY": "적극 매수",
        "BUY": "매수",
        "HOLD": "보유",
        "WAIT": "대기",
    }.get(signal, signal)


def signal_emoji(signal: str) -> str:
    return {
        "STRONG_BUY": "🟢",
        "BUY": "🔵",
        "HOLD": "🟡",
        "WAIT": "🟠",
    }.get(signal, "⚪")


def signal_color(signal: str) -> str:
    return {
        "STRONG_BUY": "#4CAF50",
        "BUY": "#2196F3",
        "HOLD": "#FF9800",
        "WAIT": "#F44336",
    }.get(signal, "#9E9E9E")


def generate_html(results: list[dict], now: datetime) -> str:
    """메인 리포트 HTML 생성."""

    # 통계
    total = len(results)
    buy_signals = len([r for r in results if r["signal"] in ("STRONG_BUY", "BUY")])
    avg_drawdown = sum(r["drawdown_pct"] for r in results) / total if total else 0
    avg_rsi = sum(r["rsi"] for r in results) / total if total else 50

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>레버리지 ETF 분할매수 가이드 - {now.strftime('%Y-%m-%d')}</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Noto Sans KR', sans-serif;
            background: linear-gradient(180deg, #0a1628 0%, #1a2744 50%, #0d1f3c 100%);
            background-attachment: fixed;
            color: #e0e6ed;
            padding: 15px;
            min-height: 100vh;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}

        .header {{
            background: linear-gradient(135deg, #1e3a5f, #2c5282);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 20px;
            border: 1px solid #3d5a80;
            text-align: center;
        }}
        .header h1 {{ font-size: 1.8em; color: #fff; text-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
        .header .sub {{ color: #90cdf4; font-size: 0.95em; margin-top: 5px; }}
        .header .date {{ color: #63b3ed; font-weight: 700; margin-top: 10px; font-size: 0.9em; }}

        .summary {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }}
        .sum-card {{
            background: linear-gradient(135deg, #1a2744, #243b5e);
            border-radius: 15px;
            padding: 16px;
            text-align: center;
            border: 1px solid #3d5a80;
        }}
        .sum-card .label {{ font-size: 0.75em; color: #90cdf4; }}
        .sum-card .value {{ font-size: 1.5em; font-weight: 700; color: #63b3ed; margin-top: 4px; }}
        .sum-card .value.green {{ color: #48bb78; }}
        .sum-card .value.red {{ color: #fc8181; }}

        .section-title {{
            color: #90cdf4;
            font-size: 1.1em;
            margin: 25px 0 12px;
            padding-left: 10px;
            border-left: 4px solid #63b3ed;
        }}

        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 15px; }}

        .card {{
            background: linear-gradient(135deg, #1a2744, #1e3050);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid #3d5a80;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}

        .card-head {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 14px;
            padding-bottom: 12px;
            border-bottom: 1px solid #2d4a6f;
        }}
        .ticker {{ font-size: 1.4em; font-weight: 700; color: #fff; }}
        .etf-name {{ font-size: 0.75em; color: #718096; margin-top: 2px; }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.7em;
            font-weight: 700;
            margin-left: 6px;
        }}
        .badge.lev {{ background: #553c9a; color: #d6bcfa; }}
        .badge.cat {{ background: #2c5282; color: #90cdf4; }}

        .signal-badge {{
            padding: 8px 14px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.85em;
            white-space: nowrap;
        }}

        .price-row {{
            display: flex;
            align-items: baseline;
            gap: 10px;
            margin-bottom: 12px;
        }}
        .price {{ font-size: 1.3em; font-weight: 700; color: #fff; }}
        .chg {{ padding: 3px 8px; border-radius: 8px; font-size: 0.85em; font-weight: 500; }}
        .up {{ background: rgba(72,187,120,0.2); color: #48bb78; }}
        .down {{ background: rgba(252,129,129,0.2); color: #fc8181; }}

        .metrics {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }}
        .metric {{
            background: rgba(45,74,111,0.5);
            padding: 8px;
            border-radius: 10px;
            text-align: center;
        }}
        .metric .ml {{ font-size: 0.65em; color: #718096; }}
        .metric .mv {{ font-size: 0.85em; font-weight: 700; color: #e2e8f0; margin-top: 2px; }}
        .metric .mv.warn {{ color: #fc8181; }}
        .metric .mv.ok {{ color: #48bb78; }}

        .grid-section {{
            background: rgba(45,74,111,0.3);
            border-radius: 10px;
            padding: 10px;
            margin-top: 10px;
        }}
        .grid-section .title {{ font-size: 0.75em; color: #90cdf4; margin-bottom: 6px; }}
        .grid-row {{
            display: flex;
            justify-content: space-between;
            font-size: 0.8em;
            padding: 3px 0;
            border-bottom: 1px solid rgba(45,74,111,0.5);
        }}
        .grid-row:last-child {{ border-bottom: none; }}
        .grid-row .lv {{ color: #718096; }}
        .grid-row .tp {{ color: #e2e8f0; font-weight: 500; }}
        .grid-row .amt {{ color: #90cdf4; }}
        .grid-row.next {{ background: rgba(99,179,237,0.15); border-radius: 6px; padding: 4px 6px; }}
        .grid-row.next .tp {{ color: #63b3ed; font-weight: 700; }}

        .details {{
            font-size: 0.72em;
            color: #4a5568;
            padding-top: 8px;
            margin-top: 8px;
            border-top: 1px solid #2d4a6f;
        }}

        .footer {{
            background: rgba(26,39,68,0.8);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            color: #4a5568;
            margin-top: 25px;
            font-size: 0.85em;
        }}
        .footer a {{ color: #63b3ed; text-decoration: none; }}

        @media (max-width: 600px) {{
            .summary {{ grid-template-columns: repeat(2, 1fr); }}
            .grid {{ grid-template-columns: 1fr; }}
            .metrics {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div style="font-size: 2em;">📊</div>
        <h1>레버리지 ETF 분할매수 가이드</h1>
        <div class="sub">그리드 전략 기반 매수 시그널 &amp; 최적 진입가 분석</div>
        <div class="date">{now.strftime('%Y-%m-%d %H:%M')} KST 업데이트</div>
    </div>

    <div class="summary">
        <div class="sum-card">
            <div class="label">분석 ETF</div>
            <div class="value">{total}개</div>
        </div>
        <div class="sum-card">
            <div class="label">매수 시그널</div>
            <div class="value {'green' if buy_signals > 0 else ''}">{buy_signals}개</div>
        </div>
        <div class="sum-card">
            <div class="label">평균 낙폭</div>
            <div class="value {'red' if avg_drawdown < -10 else ''}">{avg_drawdown:.1f}%</div>
        </div>
        <div class="sum-card">
            <div class="label">평균 RSI</div>
            <div class="value {'red' if avg_rsi < 35 else 'green' if avg_rsi < 65 else ''}">{avg_rsi:.0f}</div>
        </div>
    </div>

    <h3 class="section-title">ETF별 상세 분석</h3>
    <div class="grid">
"""

    # 시그널 강도 순 정렬
    results.sort(key=lambda x: x["strength"], reverse=True)

    for r in results:
        chg_cls = "up" if r["change_pct"] >= 0 else "down"
        sign = "+" if r["change_pct"] >= 0 else ""
        sc = signal_color(r["signal"])

        # RSI 상태
        rsi_cls = "warn" if r["rsi"] < 30 or r["rsi"] > 70 else "ok" if r["rsi"] < 50 else ""

        # 그리드 레벨 (상위 5개만)
        grid_html = ""
        if r["grid_levels"]:
            grid_html = '<div class="grid-section"><div class="title">📐 그리드 매수 레벨</div>'
            for gl in r["grid_levels"][:5]:
                is_next = r["next_buy"] and gl.level_number == r["next_buy"].level_number
                row_cls = "grid-row next" if is_next else "grid-row"
                marker = " ← 다음" if is_next else ""
                grid_html += f"""<div class="{row_cls}">
                    <span class="lv">L{gl.level_number}</span>
                    <span class="tp">${gl.target_price:.2f}{marker}</span>
                    <span class="amt">{gl.quantity}주 (${gl.budget_allocation:,.0f})</span>
                </div>"""
            if len(r["grid_levels"]) > 5:
                grid_html += f'<div class="grid-row"><span class="lv">...</span><span class="tp">+{len(r["grid_levels"]) - 5}개 레벨</span><span class="amt"></span></div>'
            grid_html += "</div>"

        # 다음 매수가 안내
        next_info = ""
        if r["next_buy"]:
            gap = (r["next_buy"].target_price - r["price"]) / r["price"] * 100
            next_info = f'다음 매수가: ${r["next_buy"].target_price:.2f} ({gap:+.1f}%)'

        html += f"""
        <div class="card">
            <div class="card-head">
                <div>
                    <span class="ticker">{r['ticker']}</span>
                    <span class="badge lev">{r['leverage']}x</span>
                    <span class="badge cat">{r['category']}</span>
                    <div class="etf-name">{r['name']} (기초: {r['underlying']})</div>
                </div>
                <span class="signal-badge" style="background:rgba({','.join(str(int(sc.lstrip('#')[i:i+2], 16)) for i in (0,2,4))},0.2); color:{sc};">
                    {signal_emoji(r['signal'])} {signal_kr(r['signal'])} ({r['strength']:.0%})
                </span>
            </div>
            <div class="price-row">
                <span class="price">${r['price']:.2f}</span>
                <span class="chg {chg_cls}">{sign}{r['change_pct']:.2f}%</span>
            </div>
            <div class="metrics">
                <div class="metric"><div class="ml">RSI</div><div class="mv {rsi_cls}">{r['rsi']:.1f}</div></div>
                <div class="metric"><div class="ml">ATH 대비</div><div class="mv warn">{r['drawdown_pct']:.1f}%</div></div>
                <div class="metric"><div class="ml">변동성</div><div class="mv">{r['vol_annual']:.1f}%</div></div>
                <div class="metric"><div class="ml">SMA 20</div><div class="mv {'ok' if r['price'] > r['sma20'] else 'warn'}">${r['sma20']:.2f}</div></div>
                <div class="metric"><div class="ml">SMA 50</div><div class="mv {'ok' if r['price'] > r['sma50'] else 'warn'}">${r['sma50']:.2f}</div></div>
                <div class="metric"><div class="ml">52주 범위</div><div class="mv">${r['low_52w']:.0f}~{r['high_52w']:.0f}</div></div>
            </div>
            {grid_html}
            <div class="details">
                ATH: ${r['ath']:.2f} | SMA200: ${r['sma200']:.2f} | 예산: ${r['suggested_budget']:,} | {next_info}
            </div>
        </div>
"""

    html += f"""
    </div>

    <div class="footer">
        <p>⚠️ 본 리포트는 교육/참고 목적이며 투자 조언이 아닙니다.</p>
        <p>레버리지 ETF는 높은 위험을 수반합니다. 투자 결정은 본인 책임입니다.</p>
        <p style="margin-top:10px;">
            <a href="https://github.com/redchoeng/etf_guide">GitHub</a> |
            자동 생성 ({now.strftime('%Y-%m-%d %H:%M')} KST)
        </p>
    </div>
</div>
</body>
</html>"""

    return html


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
            sig = f"{signal_emoji(r['signal'])} {signal_kr(r['signal'])}"
            print(f"    ${r['price']:.2f} ({r['change_pct']:+.2f}%) | {sig} | RSI {r['rsi']:.0f}")

    if not results:
        print("❌ 분석 결과 없음")
        return

    # 메인 리포트
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
    <title>Redirecting...</title>
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
