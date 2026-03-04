import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from engine.data_fetcher import ETFDataFetcher
from engine.grid_calculator import GridCalculator
from engine.backtester import GridBacktester
from dashboard.components.charts import (
    create_equity_curve_chart, create_comparison_chart,
)
from dashboard.components.formatters import fmt_currency, fmt_pct


@st.cache_data(ttl=600)
def _fetch_data(ticker: str, period: str = "max"):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.fetch_history(ticker, period=period)


def render():
    st.title("🧪 전략 백테스트")

    config = st.session_state.get("config", {})
    presets = st.session_state.get("presets", {})
    preset_list = presets.get("presets", {})
    grid_config = config.get("grid", {})
    bt_config = config.get("backtest", {})

    weighting_kr = {"equal": "균등", "linear": "선형", "exponential": "지수", "fibonacci": "피보나치"}

    st.subheader("설정")

    c1, c2 = st.columns(2)
    with c1:
        ticker = st.selectbox(
            "ETF 선택",
            options=list(preset_list.keys()),
            format_func=lambda t: f"{t} - {preset_list[t].get('name', '')}",
        )
    with c2:
        preset = preset_list.get(ticker, {})
        total_budget = st.number_input(
            "총 예산 ($)", min_value=100.0,
            value=float(preset.get("suggested_budget", 10000)),
            step=1000.0,
        )

    c3, c4, c5 = st.columns(3)
    with c3:
        num_levels = st.slider("레벨 수", 3, 30, preset.get("suggested_levels", 10))
    with c4:
        spacing = st.number_input(
            "간격 %", min_value=1.0, max_value=20.0,
            value=float(preset.get("suggested_spacing", 5.0)), step=0.5,
        )
    with c5:
        weighting = st.selectbox(
            "가중치",
            ["equal", "linear", "exponential", "fibonacci"],
            index=1,
            format_func=lambda w: weighting_kr.get(w, w),
        )

    c6, c7, c8 = st.columns(3)
    with c6:
        profit_target = st.number_input(
            "목표 수익률 %", min_value=1.0, max_value=50.0,
            value=bt_config.get("profit_target_pct", 10.0), step=1.0,
        )
    with c7:
        reinvest = st.checkbox("수익 재투자", value=bt_config.get("enable_reinvest", True))
    with c8:
        period_years = st.selectbox("백테스트 기간",
                                    [1, 2, 3, 5, 10, 15], index=3,
                                    format_func=lambda y: f"{y}년")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_years * 365)

    st.markdown("---")

    if st.button("🚀 백테스트 실행", type="primary"):
        df = _fetch_data(ticker, "max")
        if df is None or df.empty:
            st.error(f"{ticker} 데이터를 불러올 수 없습니다")
            return

        close = df["Close"].dropna()
        close_in_range = close[close.index >= pd.Timestamp(start_date)]
        if close_in_range.empty:
            st.error("선택한 기간에 데이터가 없습니다")
            return

        ref_price = float(close_in_range.iloc[0])

        calc = GridCalculator(grid_config)
        grid_levels = calc.calculate_grid(
            reference_price=ref_price,
            total_budget=total_budget,
            num_levels=num_levels,
            spacing_pct=spacing,
            weighting=weighting,
        )

        backtester = GridBacktester(bt_config)

        with st.spinner("백테스트 실행 중..."):
            try:
                result = backtester.run_backtest(
                    df, grid_levels, ticker,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    profit_target_pct=profit_target,
                    reinvest_profits=reinvest,
                    total_budget=total_budget,
                )
            except Exception as e:
                st.error(f"백테스트 오류: {e}")
                return

        # 결과 요약
        st.subheader("📊 결과 요약")

        m1, m2, m3 = st.columns(3)
        m1.metric("총 수익률", fmt_pct(result.total_return_pct))
        m2.metric("연환산 수익률", fmt_pct(result.annualized_return_pct))
        m3.metric("최종 자산", fmt_currency(result.final_value))

        m4, m5, m6 = st.columns(3)
        m4.metric("최대 낙폭", fmt_pct(result.max_drawdown_pct))
        m5.metric("최대 미실현 손실", fmt_pct(result.max_unrealized_loss_pct))
        m6.metric("실현 손익", fmt_currency(result.total_realized_pnl))

        m7, m8, m9 = st.columns(3)
        m7.metric("매수 횟수", result.num_buys)
        m8.metric("매도 횟수 (라운드)", result.num_sells)
        m9.metric("승률", fmt_pct(result.win_rate) if result.win_rate else "-")

        # 자산 곡선
        st.markdown("---")
        st.subheader("📈 자산 변화 곡선")
        fig_eq = create_equity_curve_chart(result.equity_curve, ticker, result.trades)
        st.plotly_chart(fig_eq, use_container_width=True)

        # 전략 비교
        st.markdown("---")
        st.subheader("⚖️ 전략 비교")

        with st.spinner("비교 전략 실행 중..."):
            try:
                comparison = backtester.run_comparison_backtest(
                    df, grid_levels, ticker,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    profit_target_pct=profit_target,
                )

                fig_comp = create_comparison_chart(comparison)
                st.plotly_chart(fig_comp, use_container_width=True)

                comp_rows = []
                for strategy, label in [("grid", "그리드 전략"), ("lump_sum", "일시 매수"), ("dca", "월 적립식")]:
                    data = comparison.get(strategy, {})
                    comp_rows.append({
                        "전략": label,
                        "최종 자산": data.get("final_value", 0),
                        "총 수익률": data.get("total_return_pct", 0),
                    })

                comp_df = pd.DataFrame(comp_rows)
                st.dataframe(
                    comp_df.style.format({
                        "최종 자산": "${:,.2f}",
                        "총 수익률": "{:+.2f}%",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception as e:
                st.warning(f"비교 실패: {e}")

        # 크래시 시나리오
        st.markdown("---")
        st.subheader("💥 크래시 시나리오")

        crash_periods = bt_config.get("crash_periods", [])
        if crash_periods:
            with st.spinner("크래시 시나리오 실행 중..."):
                scenarios = backtester.run_crash_scenario(
                    df, grid_levels, ticker,
                    crash_periods=crash_periods,
                    profit_target_pct=profit_target,
                )

            tabs = st.tabs([s["period_name"] for s in scenarios])
            for tab, scenario in zip(tabs, scenarios):
                with tab:
                    r = scenario.get("result")
                    if r:
                        sc1, sc2, sc3 = st.columns(3)
                        sc1.metric("수익률", fmt_pct(r.total_return_pct))
                        sc2.metric("최대 낙폭", fmt_pct(r.max_drawdown_pct))
                        sc3.metric("매수/매도", f"{r.num_buys}회 / {r.num_sells}회")

                        fig = create_equity_curve_chart(
                            r.equity_curve, f"{ticker} ({scenario['period_name']})")
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.warning(f"해당 기간 데이터 없음. {scenario.get('error', '')}")

        # 거래 내역
        st.markdown("---")
        with st.expander("📋 전체 거래 내역"):
            if result.trades:
                trade_data = []
                for t in result.trades:
                    trade_data.append({
                        "날짜": str(t.date.date()) if hasattr(t.date, 'date') else str(t.date),
                        "종류": "매수" if t.action == "BUY" else "매도",
                        "가격": f"${t.price:.2f}",
                        "수량": t.quantity,
                        "그리드 레벨": t.grid_level if t.grid_level > 0 else "-",
                        "평균 단가": f"${t.cost_basis:.2f}",
                        "손익": f"${t.pnl:.2f}" if t.pnl else "-",
                        "라운드": t.round_number,
                    })
                st.dataframe(pd.DataFrame(trade_data), use_container_width=True, hide_index=True)
