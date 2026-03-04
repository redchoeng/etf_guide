import streamlit as st
import pandas as pd
from datetime import datetime

from engine.data_fetcher import ETFDataFetcher
from storage.db import Database
from dashboard.components.formatters import fmt_currency, fmt_pct
from dashboard.components.charts import create_price_with_grid_chart


@st.cache_data(ttl=300)
def _get_current_price(ticker: str):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.get_current_price(ticker)


@st.cache_data(ttl=300)
def _fetch_data(ticker: str, period: str = "1y"):
    config = st.session_state.get("config", {})
    fetcher = ETFDataFetcher(config.get("data", {}))
    return fetcher.fetch_history(ticker, period=period)


def render():
    st.title("💼 포트폴리오")

    try:
        db = Database()
    except Exception as e:
        st.error(f"DB 오류: {e}")
        return

    # 매수 기록
    st.subheader("➕ 매수 기록")

    etf_configs = db.get_all_etf_configs()
    config_map = {c["ticker"]: c for c in etf_configs}

    if not etf_configs:
        st.info("아직 설정된 ETF가 없습니다. '그리드 설정'에서 ETF를 먼저 설정하세요.")
        st.markdown("---")
        st.subheader("빠른 입력 (설정 없이)")
        with st.form("manual_purchase"):
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                m_ticker = st.text_input("종목 코드", "QLD").upper()
            with mc2:
                m_price = st.number_input("매수가 ($)", min_value=0.01, value=50.0, step=0.01)
            with mc3:
                m_qty = st.number_input("수량", min_value=1, value=10)

            m_date = st.date_input("매수일", datetime.now())
            m_notes = st.text_input("메모 (선택)")

            if st.form_submit_button("기록 저장"):
                config_id = db.save_etf_config({
                    "ticker": m_ticker,
                    "name": m_ticker,
                    "underlying_ticker": "",
                    "leverage_factor": 2,
                    "total_budget": 10000,
                    "num_levels": 10,
                    "spacing_pct": 5.0,
                    "weighting_method": "linear",
                    "reference_price": m_price,
                    "profit_target_pct": 10.0,
                })
                db.save_purchase({
                    "etf_config_id": config_id,
                    "ticker": m_ticker,
                    "purchase_date": datetime.combine(m_date, datetime.min.time()),
                    "price": m_price,
                    "quantity": m_qty,
                    "total_cost": m_price * m_qty,
                    "notes": m_notes or None,
                })
                st.success(f"✅ {m_ticker} {m_qty}주 @ ${m_price:.2f} 기록 완료")
                st.rerun()
        return

    with st.form("add_purchase"):
        pc1, pc2, pc3, pc4 = st.columns(4)
        with pc1:
            selected_ticker = st.selectbox("ETF", [c["ticker"] for c in etf_configs])
        with pc2:
            p_price = st.number_input("매수가 ($)", min_value=0.01, value=50.0, step=0.01)
        with pc3:
            p_qty = st.number_input("수량", min_value=1, value=10)
        with pc4:
            p_date = st.date_input("매수일", datetime.now())

        pc5, pc6 = st.columns(2)
        with pc5:
            grid_levels = db.get_grid_levels(selected_ticker)
            level_options = ["없음"] + [
                f"레벨 {gl['level_number']} (${gl['target_price']:.2f})"
                for gl in grid_levels
            ]
            grid_level_sel = st.selectbox("그리드 레벨 (선택)", level_options)
        with pc6:
            p_notes = st.text_input("메모")

        if st.form_submit_button("💾 매수 기록 저장"):
            cfg = config_map.get(selected_ticker)
            grid_lv = None
            if grid_level_sel != "없음":
                grid_lv = int(grid_level_sel.split()[1])

            db.save_purchase({
                "etf_config_id": cfg["id"],
                "ticker": selected_ticker,
                "purchase_date": datetime.combine(p_date, datetime.min.time()),
                "price": p_price,
                "quantity": p_qty,
                "total_cost": p_price * p_qty,
                "grid_level": grid_lv,
                "notes": p_notes or None,
            })

            if grid_lv and grid_levels:
                for gl in grid_levels:
                    if gl["level_number"] == grid_lv:
                        db.mark_level_filled(
                            gl["id"], p_price, p_qty,
                            datetime.combine(p_date, datetime.min.time()),
                        )
                        break

            st.success(f"✅ {selected_ticker} {p_qty}주 @ ${p_price:.2f} 기록 완료")
            st.rerun()

    st.markdown("---")

    # 포트폴리오 요약
    st.subheader("📊 포트폴리오 요약")

    portfolio = db.get_portfolio_summary()
    if portfolio:
        total_invested = 0
        total_value = 0
        rows = []

        for p in portfolio:
            current_price = _get_current_price(p["ticker"])
            if current_price and p["total_shares"] > 0:
                value = p["total_shares"] * current_price
                pnl = value - p["total_cost"]
                pnl_pct = (pnl / p["total_cost"]) * 100 if p["total_cost"] > 0 else 0
            else:
                current_price = current_price or 0
                value = p["total_shares"] * current_price
                pnl = 0
                pnl_pct = 0

            total_invested += p["total_cost"]
            total_value += value

            rows.append({
                "종목": p["ticker"],
                "보유 수량": p["total_shares"],
                "평균 단가": p["avg_cost"],
                "현재가": current_price,
                "평가금": value,
                "손익": pnl,
                "수익률": pnl_pct,
            })

        total_pnl = total_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("총 투자금", fmt_currency(total_invested))
        sm2.metric("현재 평가금", fmt_currency(total_value))
        sm3.metric("총 손익", fmt_currency(total_pnl), fmt_pct(total_pnl_pct))
        sm4.metric("보유 종목", len(rows))

        if rows:
            port_df = pd.DataFrame(rows)
            st.dataframe(
                port_df.style.format({
                    "평균 단가": "${:.2f}",
                    "현재가": "${:.2f}",
                    "평가금": "${:,.2f}",
                    "손익": "${:+,.2f}",
                    "수익률": "{:+.2f}%",
                }),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("매수 기록이 없습니다.")

    st.markdown("---")

    # 그리드 현황
    if etf_configs:
        st.subheader("🔲 그리드 진행 현황")
        grid_ticker = st.selectbox(
            "ETF 선택 (그리드 뷰)",
            [c["ticker"] for c in etf_configs],
            key="grid_view_ticker",
        )

        grid_levels = db.get_grid_levels(grid_ticker)
        if grid_levels:
            filled = {gl["level_number"] for gl in grid_levels if gl.get("is_filled")}
            total_levels = len(grid_levels)
            filled_count = len(filled)

            st.progress(filled_count / total_levels if total_levels > 0 else 0)
            st.caption(f"{filled_count} / {total_levels} 레벨 체결")

            gl_data = []
            for gl in grid_levels:
                status = "✅ 체결" if gl.get("is_filled") else "⬜ 대기"
                gl_data.append({
                    "레벨": gl["level_number"],
                    "상태": status,
                    "목표가": gl["target_price"],
                    "배정액": gl["budget_allocation"],
                    "목표 수량": gl["target_quantity"],
                    "체결가": gl.get("filled_price") or "-",
                    "체결 수량": gl.get("filled_quantity") or "-",
                })

            st.dataframe(pd.DataFrame(gl_data), use_container_width=True, hide_index=True)

            df_chart = _fetch_data(grid_ticker, "1y")
            if df_chart is not None and not df_chart.empty:
                fig = create_price_with_grid_chart(df_chart, grid_levels, grid_ticker, filled)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"{grid_ticker}의 그리드가 아직 설정되지 않았습니다. '그리드 설정'에서 설정하세요.")

    st.markdown("---")

    # 매수 내역
    st.subheader("📜 매수 내역")

    filter_ticker = st.selectbox(
        "종목 필터",
        ["전체"] + [c["ticker"] for c in etf_configs],
        key="history_filter",
    )

    purchases = db.get_purchases(ticker=filter_ticker if filter_ticker != "전체" else None)
    if purchases:
        ph_data = []
        for p in purchases:
            ph_data.append({
                "날짜": str(p["purchase_date"].date()) if hasattr(p["purchase_date"], 'date') else str(p["purchase_date"]),
                "종목": p["ticker"],
                "매수가": p["price"],
                "수량": p["quantity"],
                "총 비용": p["total_cost"],
                "그리드 레벨": p.get("grid_level") or "-",
                "메모": p.get("notes") or "",
            })

        ph_df = pd.DataFrame(ph_data)
        st.dataframe(
            ph_df.style.format({
                "매수가": "${:.2f}",
                "총 비용": "${:,.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        csv = ph_df.to_csv(index=False)
        st.download_button(
            "📥 매수 내역 CSV 내보내기",
            csv,
            file_name="purchase_history.csv",
            mime="text/csv",
        )
    else:
        st.info("매수 기록이 없습니다.")
