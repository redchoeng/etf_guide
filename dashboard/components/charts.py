"""Reusable Plotly chart builders."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd


def create_price_with_grid_chart(
    df: pd.DataFrame,
    grid_levels: list,
    ticker: str = "",
    filled_levels: set = None,
) -> go.Figure:
    """Price chart with horizontal grid lines."""
    filled_levels = filled_levels or set()
    close = df["Close"].dropna()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=close.index, y=close.values,
        mode="lines", name="Price",
        line=dict(color="#2196f3", width=2),
    ))

    for gl in grid_levels:
        target = gl.target_price if hasattr(gl, "target_price") else gl.get("target_price", 0)
        level_num = gl.level_number if hasattr(gl, "level_number") else gl.get("level_number", 0)
        is_filled = level_num in filled_levels

        color = "#f44336" if is_filled else "#00c853"
        dash = "solid" if is_filled else "dash"
        label = f"L{level_num}: ${target:.2f}"
        if is_filled:
            label += " (filled)"

        fig.add_hline(
            y=target, line_dash=dash, line_color=color,
            annotation_text=label,
            annotation_position="right",
            line_width=1,
        )

    fig.update_layout(
        title=f"{ticker} Price with Grid Levels",
        xaxis_title="Date",
        yaxis_title="Price ($)",
        template="plotly_dark",
        height=500,
        showlegend=False,
    )
    return fig


def create_drawdown_chart(
    df: pd.DataFrame,
    dd_series: pd.Series,
    ticker: str = "",
) -> go.Figure:
    """Price chart with drawdown overlay."""
    close = df["Close"].dropna()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=[f"{ticker} Price", "Drawdown (%)"],
    )

    fig.add_trace(go.Scatter(
        x=close.index, y=close.values,
        mode="lines", name="Price",
        line=dict(color="#2196f3", width=1.5),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=dd_series.index, y=dd_series.values,
        fill="tozeroy", name="Drawdown",
        line=dict(color="#f44336", width=1),
        fillcolor="rgba(244,67,54,0.3)",
    ), row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=600,
        showlegend=False,
    )
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)

    return fig


def create_equity_curve_chart(
    equity_df: pd.DataFrame,
    ticker: str = "",
    trades: list = None,
) -> go.Figure:
    """Portfolio equity curve with buy markers (무한매수법: 매수만)."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=equity_df.index, y=equity_df["equity"],
        mode="lines", name="Portfolio Value",
        line=dict(color="#2196f3", width=2),
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.1)",
    ))

    if "invested" in equity_df.columns:
        invested = equity_df["invested"]
        invested_nonzero = invested[invested > 0]
        if not invested_nonzero.empty:
            fig.add_trace(go.Scatter(
                x=invested_nonzero.index, y=invested_nonzero.values,
                mode="lines", name="Invested Capital",
                line=dict(color="#ffc107", width=1, dash="dash"),
            ))

    if trades:
        buys = [t for t in trades if t.action in ("BUY", "SEED_BUY", "DCA_IDLE", "REBALANCE")]
        if buys:
            fig.add_trace(go.Scatter(
                x=[t.date for t in buys],
                y=[equity_df.loc[t.date, "equity"] if t.date in equity_df.index
                   else t.price * t.quantity for t in buys],
                mode="markers", name="Buy",
                marker=dict(symbol="triangle-up", size=10, color="#00c853"),
            ))

    fig.update_layout(
        title=f"{ticker} Backtest Equity Curve",
        xaxis_title="Date",
        yaxis_title="Portfolio Value ($)",
        template="plotly_dark",
        height=450,
    )
    return fig


def create_comparison_chart(comparison_data: dict) -> go.Figure:
    """Compare multiple strategy equity curves."""
    fig = go.Figure()

    colors = {"grid": "#2196f3", "lump_sum": "#00c853", "dca": "#ffc107"}
    names = {"grid": "무한매수", "lump_sum": "일시 매수", "dca": "월 적립식"}

    budget = comparison_data.get("total_budget", 10000)

    for strategy in ["grid", "lump_sum", "dca"]:
        data = comparison_data.get(strategy, {})
        eq = data.get("equity_curve")
        if eq is not None and not eq.empty:
            # Normalize to percentage return
            col = "equity" if "equity" in eq.columns else eq.columns[0]
            normalized = (eq[col] / budget - 1) * 100

            fig.add_trace(go.Scatter(
                x=normalized.index, y=normalized.values,
                mode="lines", name=names.get(strategy, strategy),
                line=dict(color=colors.get(strategy, "#9e9e9e"), width=2),
            ))

    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=0.5)

    fig.update_layout(
        title="Strategy Comparison (Return %)",
        xaxis_title="Date",
        yaxis_title="Return (%)",
        template="plotly_dark",
        height=450,
    )
    return fig


def create_recovery_time_chart(recovery_data: list) -> go.Figure:
    """Bar chart of recovery times by drawdown threshold."""
    thresholds = []
    avg_days = []
    worst_days = []

    for r in recovery_data:
        if r.get("avg_recovery_days") is not None:
            thresholds.append(f"-{r['threshold_pct']}%")
            avg_days.append(r["avg_recovery_days"])
            worst_days.append(r["worst_recovery_days"])

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=thresholds, y=avg_days, name="Average",
        marker_color="#2196f3",
    ))
    fig.add_trace(go.Bar(
        x=thresholds, y=worst_days, name="Worst",
        marker_color="#f44336", opacity=0.7,
    ))

    fig.update_layout(
        title="Recovery Time by Drawdown Depth",
        xaxis_title="Drawdown Threshold",
        yaxis_title="Days to Recover",
        template="plotly_dark",
        barmode="group",
        height=400,
    )
    return fig


def create_leverage_decay_chart(decay_df: pd.DataFrame, ticker: str = "") -> go.Figure:
    """Rolling leverage decay chart."""
    if decay_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Insufficient data", xref="paper", yref="paper",
                           x=0.5, y=0.5, showarrow=False)
        return fig

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.5, 0.5],
        subplot_titles=["Returns: Actual vs Expected", "Leverage Decay (%)"],
    )

    fig.add_trace(go.Scatter(
        x=decay_df.index, y=decay_df["actual_return"],
        mode="lines", name="Actual Return",
        line=dict(color="#2196f3", width=1.5),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=decay_df.index, y=decay_df["expected_return"],
        mode="lines", name="Expected Return",
        line=dict(color="#00c853", width=1.5, dash="dash"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=decay_df.index, y=decay_df["decay_pct"],
        fill="tozeroy", name="Decay",
        line=dict(color="#f44336", width=1),
        fillcolor="rgba(244,67,54,0.3)",
    ), row=2, col=1)

    fig.update_layout(
        title=f"{ticker} Leverage Decay (Rolling 1Y)",
        template="plotly_dark",
        height=600,
    )
    return fig
