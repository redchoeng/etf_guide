#!/usr/bin/env python
"""HTML 리포트 생성 진입점. 실제 로직은 report/ 패키지 참조."""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from engine.macro_analyzer import MacroAnalyzer
from engine.formatters import fmt_price
from report.analyzer import analyze_etf
from report.html_builder import generate_html

KST = timezone(timedelta(hours=9))


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_presets():
    preset_path = Path(__file__).parent / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    print("🏠 우당탕탕 딩쵱 하우스 마련 대작전 리포트 생성 시작...")
    now = datetime.now(KST)
    config = load_config()
    presets = load_presets()

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
            print(f"    {fmt_price(r['price'], r['currency'])} ({r['change_pct']:+.2f}%) | {r['score']}점 | {r['verdict']}")

    if not results:
        print("❌ 분석 결과 없음")
        return

    html = generate_html(results, macro, now)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ index.html 리포트 생성 ({len(results)}개 ETF)")

    return results


if __name__ == "__main__":
    main()
