"""HTML 리포트 생성 (토스 스타일)."""

from datetime import datetime

from engine.formatters import fmt_price, buy_phrase, verdict_color, regime_color, signal_emoji
from engine.scorer import DD_ZONES
from report.analyzer import STOP_LOSS_PCT

# 낙폭 구간별 표시 스타일: 배수가 깊을수록 붉게
_ZONE_COLORS = ["#6b7684", "#ff9500", "#f04452", "#f04452", "#d91f11", "#d91f11"]
_ZONE_LABELS = ["기본 DCA", "1.5배 매수", "2배 매수", "3배 매수", "4배 매수", "5배 매수"]

REGIME_ALLOCATION = {
    "BULL_STRONG": 0.75,
    "BULL":        0.70,
    "SIDEWAYS":    0.55,
    "CORRECTION":  0.50,
    "BEAR":        0.45,
    "CRISIS":      0.40,
}


def generate_html(results: list, macro: dict, now: datetime) -> str:
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

    noti_items = []
    noti_js_arr = []
    for r in results:
        name = r.get("display", r["ticker"])
        if r["score"] >= 70:
            noti_items.append(("buy", f"<b>{name}</b> 매수 점수 {r['score']}점 — 적극 매수 구간"))
            noti_js_arr.append(f'{{"type":"buy","ticker":"{r["ticker"]}","name":"{name}","msg":"{name} {r["score"]}점 — 적극 매수 구간"}}')
        elif r["score"] >= 60:
            noti_items.append(("buy", f"<b>{name}</b> 매수 점수 {r['score']}점 — 매수 고려"))
            noti_js_arr.append(f'{{"type":"buy","ticker":"{r["ticker"]}","name":"{name}","msg":"{name} {r["score"]}점 — 매수 고려"}}')
        if r["rsi"] < 30:
            noti_items.append(("warn", f"<b>{name}</b> RSI {r['rsi']:.0f} — 과매도 진입"))
            noti_js_arr.append(f'{{"type":"warn","ticker":"{r["ticker"]}","name":"{name}","msg":"{name} RSI {r["rsi"]:.0f} 과매도"}}')
        if r["drawdown_pct"] <= -25:
            noti_items.append(("warn", f"<b>{name}</b> 낙폭 {r['drawdown_pct']:.1f}% — 그리드 하위 레벨 도달"))
            noti_js_arr.append(f'{{"type":"warn","ticker":"{r["ticker"]}","name":"{name}","msg":"{name} 낙폭 {r["drawdown_pct"]:.1f}%"}}')
    if vix >= 30:
        noti_items.append(("warn", f"VIX {vix:.1f} — 공포 구간, 분할매수 기회"))
        noti_js_arr.append(f'{{"type":"warn","ticker":"MACRO","name":"MACRO","msg":"VIX {vix:.1f} 공포구간"}}')
    if not noti_items:
        noti_items.append(("info", "현재 특별한 매수 시그널이 없습니다. 그리드 레벨 도달 시 알려드릴게요."))

    noti_html = ""
    for ntype, text in noti_items[:6]:
        noti_html += f'<div class="noti-alert"><div class="na-dot {ntype}"></div><div class="na-text">{text}</div></div>'
    noti_js_data = "[" + ",".join(noti_js_arr) + "]"
    tickers_js = "[" + ",".join(f'"{r["ticker"]}"' for r in results) + "]"

    # JS 낙폭 계산기가 Python DD_ZONES와 항상 같은 구간을 쓰도록 생성
    dd_mult_js = "[" + ",".join(f"[{t},{m}]" for t, _, m in DD_ZONES) + "]"
    dd_colors_js = "{" + ",".join(f"'{t}':'{_ZONE_COLORS[i]}'" for i, (t, _, _m) in enumerate(DD_ZONES)) + "}"

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
.price-area{{margin-bottom:14px;position:relative}}
.price{{font-size:26px;font-weight:700;letter-spacing:-0.5px;transition:color 0.3s}}
.price-flash{{animation:priceFlash 0.6s ease}}
@keyframes priceFlash{{0%{{opacity:0.4;transform:scale(0.97)}}100%{{opacity:1;transform:scale(1)}}}}
.live-badge{{display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.2);color:#fff;font-size:10px;font-weight:600;padding:3px 10px;border-radius:10px;margin-top:6px;position:relative;z-index:1;backdrop-filter:blur(4px)}}
.live-badge .live-dot{{width:5px;height:5px;border-radius:50%;background:#4ade80;animation:pulse 1.5s infinite}}
.live-badge.live-err{{background:rgba(240,68,82,0.3);color:#fecaca}}
.price-spinner{{display:inline-block;width:12px;height:12px;border:2px solid #e5e8eb;border-top-color:#3182f6;border-radius:50%;animation:spin 0.8s linear infinite;margin-left:6px;vertical-align:middle}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.live-time{{font-size:10px;color:#8b95a1;margin-top:2px}}
.live-alert{{border-radius:10px;padding:10px 14px;margin-bottom:12px;font-size:13px;font-weight:500;display:flex;align-items:center;gap:8px;animation:alertSlide 0.4s ease}}
.live-alert.buy{{background:#e8faf0;color:#00a661}}
.live-alert.near{{background:#fff8e8;color:#b86e00}}
.live-alert.drop{{background:#fff5f5;color:#f04452}}
@keyframes alertSlide{{from{{opacity:0;transform:translateY(-8px)}}to{{opacity:1;transform:translateY(0)}}}}
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
.buy-plan.upside{{background:#f0f7ff;margin-top:8px}}
.buy-plan.upside .bp-title{{color:#3182f6}}
.buy-plan.upside tr.next-row{{background:#e8f3ff}}
.budget-input-area{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;padding:10px 12px;background:#f0f7ff;border-radius:10px}}
.budget-input-area label{{font-size:13px;font-weight:600;color:#333}}
.budget-input-area .bi-desc{{font-size:11px;color:#8b95a1;margin-top:2px}}
.input-wrap{{display:flex;align-items:center;gap:4px;background:#fff;border:1.5px solid #3182f6;border-radius:8px;padding:6px 10px}}
.input-wrap .currency{{color:#3182f6;font-weight:700;font-size:15px}}
.input-wrap input[type=number]{{border:none;outline:none;font-size:16px;font-weight:600;width:90px;text-align:right;background:transparent;color:#191f28;-moz-appearance:textfield}}
.input-wrap input[type=number]::-webkit-inner-spin-button,.input-wrap input[type=number]::-webkit-outer-spin-button{{-webkit-appearance:none;margin:0}}
.budget-bar{{display:flex;gap:4px;margin-top:8px;border-radius:8px;overflow:hidden;height:28px;font-size:11px;font-weight:500}}
.budget-bar .seg{{display:flex;align-items:center;justify-content:center}}
.budget-bar .seg.active{{background:#3182f6;color:#fff}}
.budget-bar .seg.reserve{{background:#e5e8eb;color:#4e5968}}
.sell-ref{{margin:10px 0;padding:12px;background:#fafbfc;border-radius:12px;border:1px solid #f2f4f6}}
.sell-ref .sr-title{{font-size:12px;font-weight:700;color:#6b7684;margin-bottom:8px;letter-spacing:0.5px}}
.sell-ref .sr-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}}
.sell-ref .sr-item{{padding:10px;background:#fff;border-radius:10px;text-align:center}}
.sell-ref .sr-label{{font-size:11px;color:#8b95a1;margin-bottom:4px}}
.sell-ref .sr-val{{font-size:16px;font-weight:700;color:#191f28}}
.sell-ref .sr-val.bull{{color:#00c073}}
.sell-ref .sr-val.bear{{color:#f04452}}
.sell-ref .sr-val.side{{color:#ff9500}}
.sell-ref .sr-val.profit{{color:#00c073}}
.sell-ref .sr-val.loss{{color:#f04452}}
.sell-ref .sr-sub{{font-size:10px;color:#b0b8c1;margin-top:2px}}
.sell-ref .sr-change{{display:inline-block;font-size:10px;padding:2px 6px;border-radius:4px;margin-top:4px;font-weight:600}}
.sell-ref .sr-change.warn{{background:#fff5f5;color:#f04452}}
.sell-ref .sr-change.ok{{background:#e8f8ef;color:#00c073}}
.sell-ref .sr-change.neutral{{background:#f2f4f6;color:#6b7684}}
.sell-ref .pnl-input{{display:flex;align-items:center;gap:4px;justify-content:center;margin-top:6px}}
.sell-ref .pnl-input input{{border:1px solid #e5e8eb;border-radius:6px;padding:3px 6px;width:70px;font-size:12px;text-align:right;outline:none}}
.sell-ref .pnl-input input:focus{{border-color:#3182f6}}
.sell-ref .pnl-input .sym{{font-size:12px;color:#8b95a1;font-weight:600}}
.ath-bar{{height:4px;background:#f2f4f6;border-radius:2px;margin-top:6px;overflow:hidden}}
.ath-bar .ath-fill{{height:100%;border-radius:2px;transition:width 0.3s}}
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
.weekly-buy-bar{{border-radius:10px;padding:10px 14px;font-size:14px;margin-bottom:12px;background:#e8f3ff;color:#1565C0;font-weight:600}}
.weekly-buy-bar b{{font-size:18px;color:#3182f6}}
.weekly-buy-bar.wbb-base{{background:#f2f4f6;color:#4e5968;font-weight:400}}
.weekly-guide{{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}}
.wg-row{{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#f8f9fa;border-radius:10px}}
.wg-name{{font-size:14px;font-weight:700;color:#191f28;min-width:90px}}
.wg-dd{{font-size:11px;color:#8b95a1;min-width:60px}}
.wg-mult{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px;background:#e5e8eb;color:#4e5968}}
.wg-mult.hot{{background:#fff0e0;color:#c05000}}
.wg-action{{margin-left:auto;font-size:14px;font-weight:700;color:#191f28}}
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
<div class="stat"><div class="sl">최고 점수</div><div class="sv blue">{best.get('display', best['ticker']) if best else '-'} {best['score'] if best else 0}</div></div>
</div>
</div>

<div class="section">
<div class="section-title">📅 이번 주 매수 가이드</div>
<div class="weekly-guide">"""

    for r in results:
        wm = r.get("weekly_mult", 1.0)
        dd = r.get("drawdown_pct", 0)
        name = r.get("display", r["ticker"])
        if wm > 1.0:
            action = f'{wm:.1f}배로 사세요'
            mult_badge = f'<span class="wg-mult hot">×{wm:.1f}</span>'
        else:
            action = '매수 금액대로 사세요'
            mult_badge = '<span class="wg-mult">기본</span>'
        html += f'<div class="wg-row"><span class="wg-name">{name}</span><span class="wg-dd">ATH {dd:.0f}%</span>{mult_badge}<span class="wg-action">{action}</span></div>'

    html += f"""</div>
</div>

"""

    for r in results:
        chg_cls = "up" if r["change_pct"] >= 0 else "down"
        sign = "+" if r["change_pct"] >= 0 else ""
        vc, vbg, vborder = verdict_color(r["score"])

        cur = r.get("currency", "USD")
        sym = "₩" if cur == "KRW" else "$"
        def_budget = 500000 if cur == "KRW" else 200
        budget_step = 10000 if cur == "KRW" else 10

        regime_cls = "bull" if regime in ("BULL", "BULL_STRONG") else ("bear" if regime in ("BEAR", "CRISIS", "CORRECTION") else "side")

        trend_tag = ""
        if r["trend_aligned"]:
            trend_tag = '<span class="tag trend-up">정배열</span>'
        elif r["price"] < r["sma200"]:
            trend_tag = '<span class="tag trend-dn">하락추세</span>'

        rsi_cls = "hi" if r["rsi"] < 35 else ("warn" if r["rsi"] > 65 else "")
        dd_cls = "hi" if r["drawdown_pct"] <= -15 else ""
        mom_cls = "hi" if r["mom_1m"] < -3 else ("warn" if r["mom_1m"] > 8 else "")
        sma_cls = "hi" if r["trend_aligned"] else ("warn" if r["price"] < r["sma200"] else "")

        score_pct = min(r["score"], 100)
        circumference = 2 * 3.14159 * 22
        stroke_offset = circumference * (1 - score_pct / 100)

        dd_zones = [
            (threshold, f"x{mult:.1f}", _ZONE_COLORS[i], _ZONE_LABELS[i])
            for i, (threshold, _, mult) in enumerate(DD_ZONES)
        ]
        current_dd = r["drawdown_pct"]
        dd_rows = ""
        for threshold, mult, color, label in dd_zones:
            price_at = r["ath"] * (1 + threshold / 100)
            is_active = current_dd <= threshold
            active_cls = ' class="next-row"' if is_active and (threshold == max(t for t, _, _, _ in dd_zones if current_dd <= t)) else ""
            marker = " ← 현재" if active_cls else ""
            dd_rows += f'<tr{active_cls}><td style="color:{color};font-weight:600">{threshold}%</td><td>{fmt_price(price_at, cur)}{marker}</td><td style="color:{color};font-weight:700">{mult}</td><td>{label}</td></tr>'

        buy_table = f"""<div class="buy-plan">
<div class="bp-title">낙폭 매수 가이드</div>
<div class="bp-sub">주 1회 적립식 DCA · 낙폭 깊을수록 매수 금액 증가 → 장기 보유</div>
<table>
<tr><th>ATH 낙폭</th><th>도달 가격</th><th>매수 배수</th><th>전략</th></tr>
{dd_rows}
</table>
</div>"""

        bar_color = "#00c073" if r["pos_52w"] < 30 else ("#ff9500" if r["pos_52w"] < 70 else "#f04452")
        pos_bar = f"""<div class="range-bar">
<div class="range-labels"><span>{fmt_price(r['low_52w'], cur)}</span><span>52주</span><span>{fmt_price(r['high_52w'], cur)}</span></div>
<div class="range-track"><div class="range-fill" style="width:{r['pos_52w']:.0f}%;background:{bar_color}"></div><div class="range-dot" style="left:{r['pos_52w']:.0f}%"></div></div>
</div>"""

        grid_json_levels = []
        for gl in (r["grid_levels"] or []):
            grid_json_levels.append(f'{{"l":{gl.level_number},"p":{gl.target_price:.2f},"q":{gl.quantity}}}')
        grid_data_attr = "[" + ",".join(grid_json_levels) + "]"

        upgrid_json = []
        for ugl in (r["upside_grid"] or []):
            upgrid_json.append(f'{{"l":{ugl.level_number},"p":{ugl.target_price:.2f},"q":{ugl.quantity}}}')
        upgrid_data_attr = "[" + ",".join(upgrid_json) + "]"

        config_json = f'{{"levels":{r["num_levels"]},"spacing":{r["spacing_pct"]}}}'
        wm = r.get("weekly_mult", 1.0)
        wb_base = r.get("weekly_base", 0)
        if wm > 1.0:
            wb_bar = f'<div class="weekly-buy-bar"><b>이번 주는 {wm:.1f}배로 사세요</b> 📈</div>'
        else:
            wb_bar = '<div class="weekly-buy-bar wbb-base">이번 주는 매수 금액대로 사세요</div>'
        html += f"""<div class="card" data-ticker="{r['ticker']}" data-currency="{cur}" data-grid='{grid_data_attr}' data-upgrid='{upgrid_data_attr}' data-ath="{r['ath']:.2f}" data-low52="{r['low_52w']:.2f}" data-high52="{r['high_52w']:.2f}" data-config='{config_json}' data-budget="{r['total_budget']:.0f}" data-regime="{regime}" data-weekly-base="{wb_base}" data-weekly-mult="{wm}">
{wb_bar}
<div class="card-head">
<div class="left">
<div class="ticker">{r['display']}</div>
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

<div class="price-area" id="pa-{r['ticker']}">
<span class="price" id="pr-{r['ticker']}">{fmt_price(r['price'], cur)}</span>
<span class="chg-pill {chg_cls}" id="chg-{r['ticker']}">{sign}{r['change_pct']:.2f}%</span>
</div>
<div class="live-alert" id="la-{r['ticker']}" style="display:none"></div>

{pos_bar}

<div class="metrics">
<div class="metric {rsi_cls}" onclick="showInfo('rsi')"><div class="ml">RSI</div><div class="mv">{r['rsi']:.0f}</div></div>
<div class="metric {dd_cls}" onclick="showInfo('dd')"><div class="ml">ATH 낙폭</div><div class="mv">{r['drawdown_pct']:.1f}%</div></div>
<div class="metric {mom_cls}" onclick="showInfo('mom')"><div class="ml">1개월</div><div class="mv">{r['mom_1m']:+.1f}%</div></div>
<div class="metric {sma_cls}" onclick="showInfo('sma')"><div class="ml">추세</div><div class="mv">{'정배열' if r['trend_aligned'] else '역배열'}</div></div>
</div>

<div class="budget-input-area">
<div><label>주간 투자금</label><div class="bi-desc">매주 투자할 금액 입력 → 낙폭별 매수액 자동 계산</div></div>
<div class="input-wrap">
<span class="currency">{sym}</span>
<input type="number" id="bi-{r['ticker']}" value="{def_budget}" min="{budget_step}" step="{budget_step}" oninput="recalcDCA('{r['ticker']}')">
</div>
</div>
<div id="grid-wrap-{r['ticker']}">
{buy_table}
</div>

<div class="sell-ref">
<div class="sr-title">매도 참고 지표</div>
<div class="sr-grid">
<div class="sr-item">
<div class="sr-label">시장 레짐</div>
<div class="sr-val {regime_cls}" id="regime-{r['ticker']}">{macro['regime_kr']}</div>
<div class="sr-sub" id="regime-sub-{r['ticker']}">{macro['regime']}</div>
<div class="sr-change neutral" id="regime-chg-{r['ticker']}">—</div>
</div>
<div class="sr-item">
<div class="sr-label">내 수익률</div>
<div class="sr-val" id="pnl-{r['ticker']}">—</div>
<div class="pnl-input">
<span class="sym">{sym}</span>
<input type="number" id="avgcost-{r['ticker']}" placeholder="평단가" step="0.01" oninput="calcPnL('{r['ticker']}')">
</div>
</div>
<div class="sr-item">
<div class="sr-label">ATH 대비</div>
<div class="sr-val {'loss' if r['drawdown_pct'] <= -15 else ('bear' if r['drawdown_pct'] <= -5 else 'bull')}" id="ath-dd-{r['ticker']}">{r['drawdown_pct']:.1f}%</div>
<div class="sr-sub">ATH {fmt_price(r['ath'], cur)}</div>
<div class="ath-bar"><div class="ath-fill" style="width:{max(0, 100 + r['drawdown_pct']):.0f}%;background:{'#f04452' if r['drawdown_pct'] <= -15 else ('#ff9500' if r['drawdown_pct'] <= -5 else '#00c073')}"></div></div>
</div>
</div>
</div>

<div class="info-row">
<span class="info-chip">무한매수 · 장기 보유</span>
<span class="info-chip danger">손절 {fmt_price(r['stop_loss_price'], cur)} ({STOP_LOSS_PCT:.0f}%)</span>
</div>

<div class="details">
ATH {fmt_price(r['ath'], cur)} · SMA20 {fmt_price(r['sma20'], cur)} · SMA50 {fmt_price(r['sma50'], cur)} · SMA200 {fmt_price(r['sma200'], cur)} · 3M {r['mom_3m']:+.1f}% · Vol {r['vol_annual']:.0f}%
</div>
</div>
"""

    html += f"""
<div class="strategy-box">
<h3>낙폭 적립식 매수 전략 v4</h3>
<div class="strat-item"><span class="emoji">📅</span><div class="desc"><b>기본</b>: 주 1회 정액 적립식 매수 (DCA) — 시장 상황과 무관하게 꾸준히</div></div>
<div class="strat-item"><span class="emoji">📉</span><div class="desc"><b>낙폭 -5~-10%</b>: 기본 DCA x1.5배 매수 — 조정 시작, 약간 더 담기</div></div>
<div class="strat-item"><span class="emoji">🔴</span><div class="desc"><b>낙폭 -10~-20%</b>: 기본 DCA x2배 매수 — 본격 하락, 적극 매수 구간</div></div>
<div class="strat-item"><span class="emoji">💥</span><div class="desc"><b>낙폭 -20% 이상</b>: 기본 DCA x3~5배 매수 — 폭락 = 최대 매수 기회</div></div>
<div class="strat-item"><span class="emoji">🚀</span><div class="desc"><b>상승장 진입</b>: 보유분 없으면 시드 30% 매수로 빠르게 탑승</div></div>
<div class="strat-tips">
떨어지면 더 산다 → 반등 시 폭발적 수익 · 올라도 매주 DCA로 기회 놓치지 않음<br>
매도는 직접 판단 (레짐/수익률/ATH 참고) · 장기 보유 원칙
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
{{s:'1배 나스닥 ETF 낙폭 기준',i:['🟢 -12% 이상: 매수 적극 고려 (2배 이상)','🟡 -7%~-12%: 1.5배 매수 구간','🟠 -3%~-7%: 기본 DCA','🔴 -3% 미만: 고점 영역']}},
{{s:'참고',i:['-7% 풀백은 나스닥에서 연 2~3회 발생','-20% 이하는 약세장 수준 — 최고의 기회']}}
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

const NOTI_KEY='ding_noti_enabled';
const NOTI_SENT_KEY='ding_noti_sent';
const alerts={noti_js_data};
let swReg=null;
if('serviceWorker' in navigator){{navigator.serviceWorker.register('./sw.js').then(r=>{{swReg=r;}}).catch(()=>{{}});}}
function initNoti(){{
  const enabled=localStorage.getItem(NOTI_KEY)==='true';
  const toggle=document.getElementById('notiToggle');
  const status=document.getElementById('notiStatus');
  const list=document.getElementById('notiList');
  if(enabled && Notification.permission==='granted'){{toggle.className='noti-toggle on';status.textContent='알림이 켜져 있어요';list.classList.add('show');fireAlerts();}}
  else{{toggle.className='noti-toggle off';status.textContent='알림 허용 시 시그널을 푸시로 받아요';list.classList.remove('show');}}
}}
function toggleNoti(){{
  const toggle=document.getElementById('notiToggle');
  const isOn=toggle.classList.contains('on');
  if(isOn){{localStorage.setItem(NOTI_KEY,'false');initNoti();}}
  else{{
    if(!('Notification' in window)){{document.getElementById('notiStatus').textContent='이 브라우저는 알림을 지원하지 않아요';return;}}
    Notification.requestPermission().then(p=>{{
      if(p==='granted'){{localStorage.setItem(NOTI_KEY,'true');initNoti();}}
      else{{document.getElementById('notiStatus').textContent='알림이 차단되었어요. 브라우저 설정에서 허용해주세요';}}
    }});
  }}
}}
function fireAlerts(){{
  const today=new Date().toDateString();
  const sent=localStorage.getItem(NOTI_SENT_KEY);
  if(sent===today)return;
  if(alerts.length===0)return;
  localStorage.setItem(NOTI_SENT_KEY,today);
  sendNoti('🔔 딩쵱 매수 시그널',alerts[0].msg,'ding-main');
  alerts.slice(1,4).forEach((a,i)=>{{setTimeout(()=>{{sendNoti('📊 '+(a.name||a.ticker),a.msg,'ding-'+a.ticker);}}, (i+1)*30000);}});
}}
function sendNoti(title,body,tag){{
  if(swReg){{swReg.active?.postMessage({{type:'SHOW_NOTIFICATION',title,body,tag}});}}
  else{{new Notification(title,{{body,icon:'./icons/icon-192.png',tag}});}}
}}
document.getElementById('notiBar').addEventListener('click',e=>{{if(e.target.id==='notiToggle')return;document.getElementById('notiList').classList.toggle('show');}});
initNoti();

const TICKERS={tickers_js};
function curOf(ticker){{const c=document.querySelector('.card[data-ticker="'+ticker+'"]');return c&&c.dataset.currency||'USD';}}
function moneyFmt(v,cur){{return cur==='KRW'?'₩'+Math.round(v).toLocaleString():'$'+v.toFixed(2);}}
function moneyParse(t){{const n=parseFloat(String(t).replace(/[^0-9.]/g,''));return isFinite(n)?n:0;}}
const PROXY=['https://corsproxy.io/?url=','https://api.allorigins.win/raw?url='];
let proxyIdx=0;
let liveTimer=null;
function isMarketOpen(){{const now=new Date();const et=new Date(now.toLocaleString('en-US',{{timeZone:'America/New_York'}}));const d=et.getDay(),h=et.getHours(),m=et.getMinutes();if(d===0||d===6)return false;const t=h*60+m;return t>=570&&t<=960;}}
async function fetchPrice(ticker){{
  const url=encodeURIComponent('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?interval=5m&range=1d&includePrePost=true');
  for(let i=0;i<PROXY.length;i++){{
    const px=PROXY[(proxyIdx+i)%PROXY.length];
    try{{
      const r=await fetch(px+url,{{signal:AbortSignal.timeout(8000)}});
      if(!r.ok)continue;
      const j=await r.json();
      const res=j.chart?.result?.[0];
      if(!res)continue;
      const meta=res.meta;
      const prev=meta.chartPreviousClose||meta.previousClose;
      if(!prev)continue;
      const closes=res.indicators?.quote?.[0]?.close;
      let price=meta.regularMarketPrice;
      if(closes&&closes.length>0){{for(let k=closes.length-1;k>=0;k--){{if(closes[k]!=null){{price=closes[k];break;}}}}}}
      if(!price)continue;
      return{{price,prev}};
    }}catch(e){{continue;}}
  }}
  return null;
}}
function updateCard(ticker,data){{
  const prEl=document.getElementById('pr-'+ticker);
  const chEl=document.getElementById('chg-'+ticker);
  if(!prEl||!chEl||!data)return;
  const cur=curOf(ticker);
  const oldPrice=moneyParse(prEl.textContent);
  const newPrice=data.price;
  if(!newPrice||!data.prev||data.prev===0)return;
  const chgPct=((newPrice-data.prev)/data.prev*100);
  if(!isFinite(chgPct))return;
  const sign=chgPct>=0?'+':'';
  const cls=chgPct>=0?'up':'down';
  prEl.textContent=moneyFmt(newPrice,cur);
  chEl.textContent=sign+chgPct.toFixed(2)+'%';
  chEl.className='chg-pill '+cls;
  if(Math.abs(newPrice-oldPrice)>0.005){{prEl.classList.remove('price-flash');void prEl.offsetWidth;prEl.classList.add('price-flash');}}
  checkGridAlert(ticker,newPrice,data.prev);
  if(document.getElementById('bi-'+ticker))recalcDCA(ticker);
  if(typeof calcPnL==='function')calcPnL(ticker);
  if(typeof updateAthDD==='function')updateAthDD(ticker,newPrice);
}}
function checkGridAlert(ticker,price,prev){{
  const card=document.querySelector('.card[data-ticker="'+ticker+'"]');
  const alertEl=document.getElementById('la-'+ticker);
  if(!card||!alertEl)return;
  const ath=parseFloat(card.dataset.ath)||0;
  if(!ath)return;
  const ddPct=((price-ath)/ath*100);
  let msg='',cls='';
  if(ddPct<=-30){{msg='💥 ATH 대비 '+ddPct.toFixed(1)+'% — x4~5배 적극 매수 구간';cls='buy';}}
  else if(ddPct<=-12){{msg='🔴 ATH 대비 '+ddPct.toFixed(1)+'% — x2~3배 매수 구간';cls='buy';}}
  else if(ddPct<=-7){{msg='🟠 ATH 대비 '+ddPct.toFixed(1)+'% — x1.5배 매수 구간';cls='near';}}
  else if(ddPct<=-3){{msg='🟡 ATH 대비 '+ddPct.toFixed(1)+'% — 기본 DCA 매수';cls='near';}}
  if(msg){{alertEl.innerHTML=msg;alertEl.className='live-alert '+cls;alertEl.style.display='';}}
  else{{alertEl.style.display='none';}}
}}
async function refreshAll(){{
  const badge=document.getElementById('liveBadge');
  if(badge)badge.innerHTML='<span class="price-spinner"></span> 갱신 중';
  let ok=0;
  const promises=TICKERS.map(async t=>{{const data=await fetchPrice(t);if(data){{updateCard(t,data);ok++;}}}});
  await Promise.all(promises);
  if(badge){{
    if(ok>0){{const now=new Date();const hh=String(now.getHours()).padStart(2,'0');const mm=String(now.getMinutes()).padStart(2,'0');badge.innerHTML='<span class="live-dot"></span>LIVE '+hh+':'+mm;badge.className='live-badge';}}
    else{{badge.textContent='갱신 실패';badge.className='live-badge live-err';}}
  }}
  const interval=isMarketOpen()?60000:300000;
  liveTimer=setTimeout(refreshAll,interval);
}}
const dateEl=document.querySelector('.header .date');
if(dateEl){{const lb=document.createElement('span');lb.id='liveBadge';lb.className='live-badge';lb.innerHTML='<span class="price-spinner"></span> 연결 중';dateEl.after(lb);}}
setTimeout(refreshAll,1000);
document.addEventListener('visibilitychange',()=>{{if(!document.hidden){{clearTimeout(liveTimer);refreshAll();}}}});

const DD_MULT={dd_mult_js};
const DD_COLORS={dd_colors_js};
function recalcDCA(ticker){{
  const input=document.getElementById('bi-'+ticker);
  if(!input)return;
  const weeklyBudget=parseInt(input.value)||0;
  if(weeklyBudget<10)return;
  const card=document.querySelector('.card[data-ticker="'+ticker+'"]');
  if(!card)return;
  const cur=curOf(ticker);
  const prEl=document.getElementById('pr-'+ticker);
  const price=moneyParse(prEl.textContent);
  const ath=parseFloat(card.dataset.ath)||0;
  if(!price||price<=0||!ath)return;
  const ddPct=((price-ath)/ath*100);
  const wrap=document.getElementById('grid-wrap-'+ticker);
  if(!wrap)return;
  let rows='';
  DD_MULT.forEach(([th,mult])=>{{
    const pAt=+(ath*(1+th/100)).toFixed(2);
    const amt=Math.round(weeklyBudget*mult);
    const qty=pAt>0?Math.floor(amt/pAt):0;
    const isActive=ddPct<=th;
    const isCurrent=isActive&&!DD_MULT.some(([t2,_])=>t2<th&&ddPct<=t2);
    const cls=isCurrent?' class="next-row"':'';
    const marker=isCurrent?' ← 현재':'';
    const c=DD_COLORS[th]||'#6b7684';
    rows+='<tr'+cls+'><td style="color:'+c+';font-weight:600">'+th+'%</td><td>'+moneyFmt(pAt,cur)+marker+'</td><td style="color:'+c+';font-weight:700">x'+mult.toFixed(1)+'</td><td>'+moneyFmt(amt,cur)+' ('+qty+'주)</td></tr>';
  }});
  let h='<div class="buy-plan">';
  h+='<div class="bp-title">낙폭 매수 가이드</div>';
  h+='<div class="bp-sub">주 1회 '+moneyFmt(weeklyBudget,cur)+' 적립 · 낙폭 깊을수록 매수 금액 증가 → 장기 보유</div>';
  h+='<table><tr><th>ATH 낙폭</th><th>도달 가격</th><th>매수 배수</th><th>주간 매수액</th></tr>';
  h+=rows+'</table></div>';
  wrap.innerHTML=h;
  localStorage.setItem('weekly_'+ticker,weeklyBudget);
  const card2=document.querySelector('.card[data-ticker="'+ticker+'"]');
  if(card2){{
    const wm2=parseFloat(card2.dataset.weeklyMult)||1;
    const cur2=card2.dataset.currency||'USD';
    const weeklyAmt=Math.round(weeklyBudget*wm2);
    const bar=card2.querySelector('.weekly-buy-bar');
    if(bar){{
      if(wm2>1){{
        bar.className='weekly-buy-bar';
        bar.innerHTML='<b>이번 주는 '+moneyFmt(weeklyAmt,cur2)+' 사세요</b> <span style="opacity:0.7;font-size:12px">(×'+wm2.toFixed(1)+')</span> 📈';
      }}else{{
        bar.className='weekly-buy-bar wbb-base';
        bar.innerHTML='이번 주는 <b>'+moneyFmt(weeklyAmt,cur2)+'</b> 사세요';
      }}
    }}
  }}
}}
function calcPnL(ticker){{
  const input=document.getElementById('avgcost-'+ticker);
  const pnlEl=document.getElementById('pnl-'+ticker);
  if(!input||!pnlEl)return;
  const avgCost=parseFloat(input.value);
  if(!avgCost||avgCost<=0){{pnlEl.textContent='—';pnlEl.className='sr-val';return;}}
  const prEl=document.getElementById('pr-'+ticker);
  const price=moneyParse(prEl.textContent);
  if(!price)return;
  const pnlPct=((price-avgCost)/avgCost*100);
  const sign=pnlPct>=0?'+':'';
  pnlEl.textContent=sign+pnlPct.toFixed(1)+'%';
  pnlEl.className='sr-val '+(pnlPct>=0?'profit':'loss');
  localStorage.setItem('avgcost_'+ticker,avgCost);
}}
function updateAthDD(ticker,price){{
  const card=document.querySelector('.card[data-ticker="'+ticker+'"]');
  if(!card)return;
  const ath=parseFloat(card.dataset.ath)||0;
  if(!ath)return;
  const ddPct=((price-ath)/ath*100);
  const el=document.getElementById('ath-dd-'+ticker);
  if(el){{el.textContent=ddPct.toFixed(1)+'%';el.className='sr-val '+(ddPct<=-15?'loss':(ddPct<=-5?'bear':'bull'));}}
  const bar=card.querySelector('.ath-fill');
  if(bar){{const w=Math.max(0,100+ddPct);bar.style.width=w.toFixed(0)+'%';bar.style.background=ddPct<=-15?'#f04452':(ddPct<=-5?'#ff9500':'#00c073');}}
}}
const REGIME_ORDER=['CRISIS','BEAR','CORRECTION','SIDEWAYS','BULL','BULL_STRONG'];
const REGIME_KR={{'CRISIS':'위기','BEAR':'하락장','CORRECTION':'조정','SIDEWAYS':'횡보장','BULL':'상승장','BULL_STRONG':'강한 상승장'}};
function checkRegimeChange(){{
  document.querySelectorAll('.card[data-ticker]').forEach(card=>{{
    const ticker=card.dataset.ticker;
    const curRegime=card.dataset.regime;
    const prevKey='regime_'+ticker;
    const prev=localStorage.getItem(prevKey);
    const chgEl=document.getElementById('regime-chg-'+ticker);
    if(!chgEl)return;
    if(prev&&prev!==curRegime){{
      const pi=REGIME_ORDER.indexOf(prev);const ci=REGIME_ORDER.indexOf(curRegime);
      if(ci<pi){{chgEl.textContent='⚠ '+(REGIME_KR[prev]||prev)+' → '+(REGIME_KR[curRegime]||curRegime);chgEl.className='sr-change warn';}}
      else{{chgEl.textContent='▲ '+(REGIME_KR[prev]||prev)+' → '+(REGIME_KR[curRegime]||curRegime);chgEl.className='sr-change ok';}}
    }}else if(!prev){{chgEl.textContent='변동 없음';chgEl.className='sr-change neutral';}}
    localStorage.setItem(prevKey,curRegime);
  }});
}}
document.addEventListener('DOMContentLoaded',()=>{{
  document.querySelectorAll('.card[data-ticker]').forEach(card=>{{
    const t=card.dataset.ticker;
    const saved=localStorage.getItem('weekly_'+t);
    const input=document.getElementById('bi-'+t);
    if(saved&&input){{input.value=saved;}}
    if(input)recalcDCA(t);
    const avgSaved=localStorage.getItem('avgcost_'+t);
    if(avgSaved){{const avgInput=document.getElementById('avgcost-'+t);if(avgInput){{avgInput.value=avgSaved;calcPnL(t);}}}}
  }});
  checkRegimeChange();
}});
</script>
</body></html>"""

    return html
