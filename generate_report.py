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

    # 추정 iNAV — 한국장 장외 시간에만 (장중엔 실시간 가격이 있으므로 불필요)
    import os
    inav = {}
    if not (9 <= now.hour < 16) or os.environ.get("FORCE_INAV"):
        try:
            from alerts.holdings import _load_snapshot, _ticker_of, _fetch_us_prices
            from alerts.inav import estimate_inav
            snapshot = _load_snapshot()
            tickers = set()
            for t in presets.get("presets", {}):
                entry = snapshot.get(t.split(".")[0]) or {}
                for n in (entry.get("holdings") or {}):
                    tk = _ticker_of(n)
                    if tk:
                        tickers.add(tk)
            if tickers:
                print("  추정 iNAV 계산 중...")
                prices = _fetch_us_prices(sorted(tickers | {"KRW=X"}))
                for r in results:
                    iv = estimate_inav(r["ticker"], snapshot, prices,
                                       kr_close=r["price"], ath=r["ath"])
                    if iv:
                        inav[r["ticker"]] = iv
                        print(f"    {r['display']}: 예상 ₩{iv['est']:,.0f} "
                              f"(바스켓 {iv['r_basket']:+.1f}% 환율 {iv['r_fx']:+.1f}%)")
        except Exception as e:
            print(f"  iNAV 추정 스킵: {e}")

    html = generate_html(results, macro, now, inav)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ index.html 리포트 생성 ({len(results)}개 ETF)")

    return results


if __name__ == "__main__":
    main()
