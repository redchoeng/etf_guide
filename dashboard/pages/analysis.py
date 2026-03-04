import streamlit as st
import pandas as pd

from engine.data_fetcher import ETFDataFetcher
from engine.drawdown_analyzer import DrawdownAnalyzer
from engine.volatility_analyzer import VolatilityAnalyzer
from dashboard.components.charts import (
    create_drawdown_chart, create_recovery_time_chart, create_leverage_decay_chart,
)
from dashboard.components.formatters import fmt_currency, fmt_pct


@st.cache_data(ttl=600)
def _fetch_data(ticker: str, period: str = "max"):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.fetch_history(ticker, period=period)


def render():
    st.title("📈 역사적 분석")

    config = st.session_state.get("config", {})
    presets = st.session_state.get("presets", {})
    preset_list = presets.get("presets", {})
    underlying_pairs = presets.get("underlying_pairs", {})

    col1, col2 = st.columns([1, 1])
    with col1:
        ticker = st.selectbox(
            "ETF 선택",
            options=list(preset_list.keys()),
            format_func=lambda t: f"{t} - {preset_list[t].get('name', '')}",
        )
    with col2:
        period = st.selectbox("기간", ["1y", "2y", "5y", "10y", "max"],
                              index=4, format_func=lambda p: {
                "1y": "1년", "2y": "2년", "5y": "5년", "10y": "10년", "max": "전체"
            }.get(p, p))

    preset = preset_list.get(ticker, {})
    underlying = underlying_pairs.get(ticker, preset.get("underlying", ""))
    leverage = preset.get("leverage", 2)

    df = _fetch_data(ticker, period)
    if df is None or df.empty:
        st.error(f"{ticker} 데이터를 불러올 수 없습니다")
        return

    # 낙폭 분석
    st.markdown("---")
    st.subheader("📉 낙폭 (Drawdown) 분석")

    dd_analyzer = DrawdownAnalyzer(config.get("drawdown", {}))
    dd_result = dd_analyzer.analyze(df, ticker)

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("최대 낙폭", fmt_pct(dd_result["max_drawdown"]))
    mc2.metric("현재 낙폭", fmt_pct(dd_result["current_drawdown"]))
    mc3.metric("역대 최고가", fmt_currency(dd_result["ath_price"]))
    mc4.metric("현재가", fmt_currency(dd_result["current_price"]))

    fig_dd = create_drawdown_chart(df, dd_result["drawdown_series"], ticker)
    st.plotly_chart(fig_dd, use_container_width=True)

    events = dd_result.get("drawdown_events", [])
    if events:
        st.subheader("주요 낙폭 이벤트")
        event_data = []
        for e in events:
            event_data.append({
                "이벤트": e.label or "미명명",
                "시작일": str(e.start_date.date()) if hasattr(e.start_date, 'date') else str(e.start_date),
                "저점일": str(e.trough_date.date()) if hasattr(e.trough_date, 'date') else str(e.trough_date),
                "낙폭": f"{e.drawdown_pct:.1f}%",
                "고점가": f"${e.peak_price:.2f}",
                "저점가": f"${e.trough_price:.2f}",
                "하락 소요일": e.duration_to_trough_days,
                "회복 소요일": e.recovery_days if e.recovery_days else "미회복",
            })
        st.dataframe(pd.DataFrame(event_data), use_container_width=True, hide_index=True)

    # 회복 기간 분석
    st.markdown("---")
    st.subheader("⏱️ 낙폭별 회복 기간")

    recovery_stats = dd_analyzer.recovery_time_analysis(df)
    fig_recovery = create_recovery_time_chart(recovery_stats)
    st.plotly_chart(fig_recovery, use_container_width=True)

    with st.expander("회복 기간 상세"):
        rec_data = []
        for r in recovery_stats:
            if r["occurrences"] > 0:
                rec_data.append({
                    "낙폭 기준": f"-{r['threshold_pct']}%",
                    "발생 횟수": r["occurrences"],
                    "평균 회복일": r["avg_recovery_days"],
                    "중앙값 회복일": r["median_recovery_days"],
                    "최장 회복일": r["worst_recovery_days"],
                    "최단 회복일": r["best_recovery_days"],
                })
        if rec_data:
            st.dataframe(pd.DataFrame(rec_data), use_container_width=True, hide_index=True)

    # 변동성
    st.markdown("---")
    st.subheader("📊 변동성 지표")

    vol_analyzer = VolatilityAnalyzer(config.get("data", {}))
    vol_result = vol_analyzer.calculate_volatility(df)
    var_result = vol_analyzer.calculate_var(df)

    if vol_result:
        vc1, vc2, vc3, vc4 = st.columns(4)
        vc1.metric("연환산 변동성", f"{vol_result.get('annualized_vol', 0):.1f}%")
        vc2.metric("샤프 비율", f"{vol_result.get('sharpe_ratio', 0):.2f}")
        vc3.metric("최대 일일 상승", fmt_pct(vol_result.get("max_daily_gain", 0)))
        vc4.metric("최대 일일 하락", fmt_pct(vol_result.get("max_daily_loss", 0)))

        vc5, vc6, vc7, vc8 = st.columns(4)
        vc5.metric("20일 변동성", f"{vol_result.get('daily_vol_20d', 0):.1f}%")
        vc6.metric("60일 변동성", f"{vol_result.get('daily_vol_60d', 0):.1f}%")
        vc7.metric("하락일 비율", f"{vol_result.get('pct_days_negative', 0):.1f}%")
        if var_result:
            vc8.metric("일일 VaR 95%", fmt_pct(var_result.get("daily_var_95", 0)))

    # 레버리지 디케이
    st.markdown("---")
    st.subheader("🔄 레버리지 디케이 분석")

    if underlying:
        df_underlying = _fetch_data(underlying, period)
        if df_underlying is not None and not df_underlying.empty:
            comparison = dd_analyzer.compare_leveraged_vs_underlying(
                df, df_underlying, leverage
            )

            lc1, lc2, lc3 = st.columns(3)
            lc1.metric(
                f"{ticker} 총 수익률",
                fmt_pct(comparison["leveraged_total_return"]),
            )
            lc2.metric(
                f"{underlying} 총 수익률",
                fmt_pct(comparison["underlying_total_return"]),
            )
            lc3.metric(
                "레버리지 디케이",
                fmt_pct(comparison["leverage_decay"]),
                help=f"실제 {leverage}배 수익률과 이론적 수익률의 차이",
            )

            st.caption(f"분석 기간: {comparison['period_start']} ~ {comparison['period_end']}")

            decay_df = dd_analyzer.calculate_leverage_decay(
                df, df_underlying, leverage, window_days=252
            )
            fig_decay = create_leverage_decay_chart(decay_df, ticker)
            st.plotly_chart(fig_decay, use_container_width=True)
        else:
            st.warning(f"기초 지수 ETF ({underlying}) 데이터를 불러올 수 없습니다.")
    else:
        st.info("디케이 분석을 위한 기초 지수 ETF가 설정되지 않았습니다.")
