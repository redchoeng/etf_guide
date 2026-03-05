import streamlit as st
import pandas as pd

from engine.data_fetcher import ETFDataFetcher
from engine.grid_calculator import GridCalculator
from engine.drawdown_analyzer import DrawdownAnalyzer
from dashboard.components.charts import create_price_with_grid_chart
from dashboard.components.formatters import fmt_currency, fmt_pct


@st.cache_data(ttl=300)
def _fetch_data(ticker: str, period: str = "max"):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.fetch_history(ticker, period=period)


@st.cache_data(ttl=300)
def _get_current_price(ticker: str):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.get_current_price(ticker)


def render():
    st.title("⚙️ 무한매수 그리드 설정")

    config = st.session_state.get("config", {})
    presets = st.session_state.get("presets", {})
    preset_list = presets.get("presets", {})
    grid_config = config.get("grid", {})

    # ETF 선택
    st.subheader("ETF 선택")
    col1, col2 = st.columns([1, 2])

    with col1:
        use_preset = st.radio("방식", ["프리셋", "직접 입력"])

    with col2:
        if use_preset == "프리셋":
            ticker = st.selectbox(
                "ETF 선택",
                options=list(preset_list.keys()),
                format_func=lambda t: f"{t} - {preset_list[t].get('name', '')}",
            )
            preset = preset_list.get(ticker, {})
            underlying = preset.get("underlying", "")
            leverage = preset.get("leverage", 2)
        else:
            ticker = st.text_input("종목 코드", "QLD").upper()
            underlying = st.text_input("기초 지수 ETF", "QQQ").upper()
            leverage = st.selectbox("레버리지 배율", [2, 3], index=0)
            preset = {}

    current_price = _get_current_price(ticker)
    if current_price:
        st.info(f"**{ticker}** 현재가: **{fmt_currency(current_price)}**")
    else:
        current_price = st.number_input("현재가 직접 입력 ($)", min_value=0.01, value=50.0)

    st.markdown("---")

    # 그리드 파라미터
    st.subheader("그리드 파라미터")

    weighting_kr = {
        "equal": "균등 - 모든 레벨 동일 비중",
        "linear": "선형 - 하락할수록 비중 증가 (추천)",
        "exponential": "지수 - 하락할수록 급격히 비중 증가",
        "fibonacci": "피보나치 - 피보나치 수열 비중",
    }

    c1, c2, c3 = st.columns(3)
    with c1:
        total_budget = st.number_input(
            "총 투자 예산 ($)",
            min_value=100.0,
            value=float(preset.get("suggested_budget", 10000)),
            step=1000.0,
        )
    with c2:
        num_levels = st.slider(
            "그리드 레벨 수",
            min_value=3,
            max_value=grid_config.get("max_levels", 40),
            value=preset.get("suggested_levels", grid_config.get("default_levels", 10)),
        )
    with c3:
        weighting = st.selectbox(
            "가중치 방식",
            options=list(GridCalculator.WEIGHTING_METHODS.keys()),
            format_func=lambda w: weighting_kr.get(w, w),
            index=1,
        )

    ref_option = st.radio(
        "기준 가격",
        ["현재가", "역대 최고가 (ATH)", "52주 최고가", "직접 입력"],
        horizontal=True,
    )

    reference_price = current_price
    if ref_option == "직접 입력":
        reference_price = st.number_input("기준 가격 ($)", min_value=0.01, value=current_price)
    elif ref_option in ("역대 최고가 (ATH)", "52주 최고가"):
        period = "max" if ref_option.startswith("역대") else "1y"
        df = _fetch_data(ticker, period)
        if df is not None and not df.empty:
            reference_price = float(df["Close"].max())
            st.info(f"기준 가격 ({ref_option}): {fmt_currency(reference_price)}")

    st.markdown("---")
    auto_calc = st.checkbox("📊 역사적 최대 낙폭 기반으로 간격 자동 계산")

    if auto_calc:
        df_full = _fetch_data(ticker, "max")
        if df_full is not None and not df_full.empty:
            analyzer = DrawdownAnalyzer(config.get("drawdown", {}))
            dd_result = analyzer.analyze(df_full, ticker)
            max_dd = dd_result["max_drawdown"]

            coverage = st.slider("낙폭 커버리지 (%)", 50, 100, 80,
                                 help="역사적 최대 낙폭의 몇 %까지 커버할지 설정")
            effective_dd = abs(max_dd) * (coverage / 100)
            spacing_pct = effective_dd / num_levels

            st.success(
                f"**{ticker}** 역대 최대 낙폭: **{max_dd:.1f}%** | "
                f"커버리지 {coverage}% = **{effective_dd:.1f}%** | "
                f"{num_levels}레벨 → **{spacing_pct:.2f}% 간격**"
            )
        else:
            st.warning("과거 데이터를 불러올 수 없습니다. 간격을 수동으로 입력하세요.")
            spacing_pct = preset.get("suggested_spacing", grid_config.get("default_spacing_pct", 5.0))
    else:
        spacing_pct = st.number_input(
            "레벨 간 간격 (%)",
            min_value=0.5,
            max_value=30.0,
            value=float(preset.get("suggested_spacing", grid_config.get("default_spacing_pct", 5.0))),
            step=0.5,
        )

    st.markdown("---")

    # 그리드 계산
    calc = GridCalculator(grid_config)
    grid_levels = calc.calculate_grid(
        reference_price=reference_price,
        total_budget=total_budget,
        num_levels=num_levels,
        spacing_pct=spacing_pct,
        weighting=weighting,
    )

    # 그리드 미리보기
    st.subheader("📋 그리드 미리보기")

    grid_data = []
    for gl in grid_levels:
        grid_data.append({
            "레벨": gl.level_number,
            "하락률": f"{gl.drop_pct:.1f}%",
            "매수 목표가": gl.target_price,
            "배정 금액": gl.budget_allocation,
            "배정 비율": f"{gl.budget_pct:.1f}%",
            "매수 수량": gl.quantity,
            "누적 투자금": gl.cumulative_budget,
            "누적 주식수": gl.cumulative_shares,
            "평균 단가": gl.avg_cost_basis,
        })

    grid_df = pd.DataFrame(grid_data)
    st.dataframe(
        grid_df.style.format({
            "매수 목표가": "${:.2f}",
            "배정 금액": "${:,.2f}",
            "누적 투자금": "${:,.2f}",
            "평균 단가": "${:.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    if grid_levels:
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("총 배정 금액", fmt_currency(sum(gl.budget_allocation for gl in grid_levels)))
        sc2.metric("전부 체결시", f"{grid_levels[-1].cumulative_shares}주")
        sc3.metric("전부 체결 평단가", fmt_currency(grid_levels[-1].avg_cost_basis))
        sc4.metric("최대 하락 구간", f"{grid_levels[-1].drop_pct:.1f}%")

    st.markdown("---")

    # 레벨별 평단가 (참고용)
    st.subheader("📊 레벨별 평균 단가")
    st.caption("♾️ 무한매수법: 각 레벨까지 체결되었을 때의 평균 단가를 참고하세요. 익절 없이 장기 보유합니다.")

    recovery = calc.calculate_recovery_targets(grid_levels, 10.0)

    recovery_data = []
    for r in recovery:
        recovery_data.append({
            "체결 레벨": r["levels_filled"],
            "총 투자금": r["total_invested"],
            "총 주식수": r["total_shares"],
            "평균 단가": r["avg_cost"],
        })

    recovery_df = pd.DataFrame(recovery_data)
    st.dataframe(
        recovery_df.style.format({
            "총 투자금": "${:,.2f}",
            "평균 단가": "${:.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # 가격 차트 + 그리드 라인
    st.subheader("📊 가격 차트 + 그리드 라인")
    chart_period = st.selectbox("차트 기간", ["6mo", "1y", "2y", "5y", "max"], index=2)
    df_chart = _fetch_data(ticker, chart_period)

    if df_chart is not None and not df_chart.empty:
        fig = create_price_with_grid_chart(df_chart, grid_levels, ticker)
        st.plotly_chart(fig, use_container_width=True)

    # 내보내기
    st.markdown("---")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        csv = grid_df.to_csv(index=False)
        st.download_button(
            "📥 그리드 CSV 내보내기",
            csv,
            file_name=f"{ticker}_grid_{num_levels}levels.csv",
            mime="text/csv",
        )
    with col_exp2:
        rec_csv = recovery_df.to_csv(index=False)
        st.download_button(
            "📥 평균 단가 CSV",
            rec_csv,
            file_name=f"{ticker}_avg_cost.csv",
            mime="text/csv",
        )

    # DB 저장
    st.markdown("---")
    if st.button("💾 그리드 설정 저장"):
        try:
            from storage.db import Database
            db = Database()

            existing = db.get_etf_config(ticker)
            config_data = {
                "ticker": ticker,
                "name": preset.get("name", ticker),
                "underlying_ticker": underlying,
                "leverage_factor": leverage,
                "total_budget": total_budget,
                "num_levels": num_levels,
                "spacing_pct": spacing_pct,
                "weighting_method": weighting,
                "reference_price": reference_price,
                "profit_target_pct": 0,  # 무한매수법: 익절 없음
            }

            if existing:
                db.update_etf_config(ticker, config_data)
                config_id = existing["id"]
            else:
                config_id = db.save_etf_config(config_data)

            level_data = []
            for gl in grid_levels:
                level_data.append({
                    "level_number": gl.level_number,
                    "drop_pct": gl.drop_pct,
                    "target_price": gl.target_price,
                    "budget_allocation": gl.budget_allocation,
                    "budget_pct": gl.budget_pct,
                    "target_quantity": gl.quantity,
                })
            db.save_grid_levels(config_id, level_data)
            st.success(f"✅ {ticker} 그리드 설정 저장 완료 ({len(level_data)}레벨)")

        except Exception as e:
            st.error(f"저장 실패: {e}")
