import streamlit as st
import pandas as pd

from engine.data_fetcher import ETFDataFetcher
from engine.signal_generator import SignalGenerator
from storage.db import Database
from dashboard.components.formatters import (
    fmt_currency, fmt_pct, signal_color, signal_emoji, signal_kr,
)


@st.cache_data(ttl=300)
def _fetch_etf_data(ticker: str, period: str = "1y"):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.fetch_history(ticker, period=period)


@st.cache_data(ttl=300)
def _get_current_price(ticker: str):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.get_current_price(ticker)


def render():
    st.title("🏠 개요")

    config = st.session_state.get("config", {})
    presets = st.session_state.get("presets", {})
    preset_list = presets.get("presets", {})

    try:
        db = Database()
        portfolio = db.get_portfolio_summary()
        etf_configs = db.get_all_etf_configs()
    except Exception:
        portfolio = []
        etf_configs = []

    # 포트폴리오 스냅샷
    st.subheader("포트폴리오 스냅샷")
    if portfolio:
        total_invested = sum(p["total_cost"] for p in portfolio)
        total_value = 0
        for p in portfolio:
            price = _get_current_price(p["ticker"])
            if price:
                total_value += p["total_shares"] * price
            else:
                total_value += p["total_cost"]

        pnl = total_value - total_invested
        pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 투자금", fmt_currency(total_invested))
        c2.metric("현재 가치", fmt_currency(total_value))
        c3.metric("수익/손실", fmt_currency(pnl), fmt_pct(pnl_pct))
        c4.metric("보유 ETF 수", len(portfolio))
    else:
        st.info("아직 매수 기록이 없습니다. '그리드 설정'에서 ETF를 설정하고, '포트폴리오'에서 매수를 기록하세요.")

    st.markdown("---")

    # ETF 현황 카드
    st.subheader("ETF 실시간 현황")

    default_tickers = ["QLD", "SSO", "TQQQ", "UPRO"]
    selected_tickers = st.multiselect(
        "모니터링할 ETF 선택",
        options=list(preset_list.keys()),
        default=[t for t in default_tickers if t in preset_list],
    )

    if selected_tickers:
        cols = st.columns(min(len(selected_tickers), 4))
        signal_gen = SignalGenerator(config.get("signals", {}))

        for idx, ticker in enumerate(selected_tickers):
            col = cols[idx % len(cols)]
            preset = preset_list.get(ticker, {})

            with col:
                st.markdown(f"### {ticker}")
                st.caption(preset.get("name", ticker))

                df = _fetch_etf_data(ticker, "1y")
                if df is not None and not df.empty:
                    signals = signal_gen.generate_signals(df)
                    price = signals.get("current_price", 0)
                    rsi = signals.get("rsi_14", 0)
                    dd = signals.get("current_drawdown_pct", 0)
                    overall = signals.get("overall_signal", "HOLD")
                    strength = signals.get("signal_strength", 0.5)

                    st.metric("현재가", fmt_currency(price))
                    st.metric("RSI", f"{rsi:.1f}")
                    st.metric("고점 대비", fmt_pct(dd))

                    color = signal_color(overall)
                    kr = signal_kr(overall)
                    st.markdown(
                        f"<div style='background-color:{color};padding:8px;border-radius:5px;"
                        f"text-align:center;color:white;font-weight:bold;'>"
                        f"{signal_emoji(overall)} {kr} ({strength:.0%})</div>",
                        unsafe_allow_html=True,
                    )

                    if signals.get("reasons"):
                        with st.expander("시그널 상세"):
                            for reason in signals["reasons"]:
                                st.write(f"- {reason}")
                else:
                    st.warning(f"{ticker} 데이터를 불러올 수 없습니다")

    st.markdown("---")

    # 시그널 요약 테이블
    st.subheader("시그널 종합 요약")
    if selected_tickers:
        signal_gen = SignalGenerator(config.get("signals", {}))
        rows = []
        for ticker in selected_tickers:
            df = _fetch_etf_data(ticker, "1y")
            if df is not None and not df.empty:
                sig = signal_gen.generate_signals(df)
                rows.append({
                    "종목": ticker,
                    "현재가": sig.get("current_price", 0),
                    "RSI": sig.get("rsi_14", 0),
                    "SMA 시그널": sig.get("sma_signal", "-"),
                    "낙폭 %": sig.get("current_drawdown_pct", 0),
                    "판정": signal_kr(sig.get("overall_signal", "-")),
                    "강도": sig.get("signal_strength", 0),
                })

        if rows:
            signal_df = pd.DataFrame(rows)
            st.dataframe(
                signal_df.style.format({
                    "현재가": "${:.2f}",
                    "RSI": "{:.1f}",
                    "낙폭 %": "{:+.2f}%",
                    "강도": "{:.0%}",
                }),
                use_container_width=True,
                hide_index=True,
            )
