"""낙폭 기반 적립식 매수 백테스터.

적립식 DCA + 떨어지면 더 사는 컨셉.
매수만 하고 익절하지 않는 '무한매수법' 전략.

핵심 원리:
  - 기본: 주 1회 정액 적립식 매수 (DCA)
  - 낙폭 깊을수록 매수 금액 증가 (낙폭 배수)
  - 상승장 진입 시 시드매수로 참여
  - 장기 보유, 익절 없음 → 복리 효과 극대화
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from engine.grid_calculator import GridCalculator, GridLevel

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Single trade in backtest."""
    date: datetime
    action: str  # BUY, SEED_BUY, REBALANCE, DCA_IDLE
    price: float
    quantity: int
    grid_level: int
    cost_basis: float
    pnl: float = 0.0
    round_number: int = 1
    regime: str = ""
    note: str = ""


@dataclass
class BacktestResult:
    """Complete backtest result."""
    start_date: datetime
    end_date: datetime
    ticker: str
    total_budget: float
    final_value: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    max_unrealized_loss_pct: float
    num_buys: int
    num_sells: int
    num_rounds: int
    total_realized_pnl: float
    win_rate: float
    avg_cost_basis: float
    trades: list[BacktestTrade]
    equity_curve: pd.DataFrame
    grid_config: dict
    seed_buys: int = 0
    rebalances: int = 0
    regime_changes: int = 0
    leverage_decay_pct: float = 0.0
    idle_dca_buys: int = 0
    upside_buys: int = 0


# ── 레짐별 투자비율 ──────────────────────────────────────

REGIME_ALLOCATION = {
    "BULL_STRONG": 0.75,
    "BULL":        0.70,
    "SIDEWAYS":    0.55,
    "CORRECTION":  0.50,
    "BEAR":        0.45,
    "CRISIS":      0.40,
}


def detect_regime(close: pd.Series, idx: int) -> str:
    """SMA + 변동성 기반 레짐 판별 (백테스트용).

    실시간은 MacroAnalyzer(VIX+금리)를 쓰지만,
    백테스트는 가격 데이터만으로 레짐을 추정합니다.
    """
    if idx < 50:
        return "SIDEWAYS"

    price = float(close.iloc[idx])
    sma50 = float(close.iloc[max(0, idx - 50):idx + 1].mean())

    if idx >= 200:
        sma200 = float(close.iloc[max(0, idx - 200):idx + 1].mean())
    else:
        sma200 = float(close.iloc[:idx + 1].mean())

    # 20일 변동성 (연환산)
    if idx >= 20:
        returns = close.iloc[max(0, idx - 20):idx + 1].pct_change().dropna()
        vol_20 = float(returns.std() * np.sqrt(252) * 100) if len(returns) > 1 else 30.0
    else:
        vol_20 = 30.0

    # 1개월 모멘텀
    if idx >= 22:
        mom_1m = (price / float(close.iloc[idx - 22]) - 1) * 100
    else:
        mom_1m = 0.0

    # 레짐 판별
    if price > sma200 and sma50 > sma200:
        if vol_20 < 25 and mom_1m > 2:
            return "BULL_STRONG"
        return "BULL"
    elif price < sma200 and sma50 < sma200:
        if vol_20 > 40 or mom_1m < -15:
            return "CRISIS"
        if vol_20 > 30:
            return "BEAR"
        return "CORRECTION"
    elif price < sma200:
        return "CORRECTION"
    else:
        return "SIDEWAYS"


class GridBacktester:
    """낙폭 기반 적립식 매수 백테스터.

    기본: 주 1회 DCA 적립식 매수
    하락 시: 낙폭 배수만큼 매수 금액 증가
    상승장: 시드매수로 빠르게 참여
    """

    # 낙폭 구간별 매수 배수 (ATH 대비)
    DRAWDOWN_MULTIPLIER = [
        # (낙폭 이상, 매수 배수)
        (-5,  1.0),   # -5% 미만: 기본 DCA
        (-10, 1.5),   # -5~-10%: 1.5배
        (-20, 2.0),   # -10~-20%: 2배
        (-30, 3.0),   # -20~-30%: 3배
        (-40, 4.0),   # -30~-40%: 4배
        (-50, 5.0),   # -40~-50%: 5배
    ]

    def __init__(self, config: dict = None):
        config = config or {}

    @staticmethod
    def _get_dd_multiplier(dd_pct: float) -> float:
        """낙폭(%)에 해당하는 매수 배수 반환."""
        mult = 1.0
        for threshold, m in GridBacktester.DRAWDOWN_MULTIPLIER:
            if dd_pct <= threshold:
                mult = m
        return mult

    def run_backtest(
        self,
        df: pd.DataFrame,
        grid_levels: list[GridLevel],
        ticker: str = "",
        start_date: str = None,
        end_date: str = None,
        profit_target_pct: float = 10.0,
        reinvest_profits: bool = True,
        total_budget: float = None,
    ) -> BacktestResult:
        """낙폭 기반 적립식 매수 백테스트 (매수만, 익절 없음)."""
        close = df["Close"].dropna()

        if start_date:
            close = close[close.index >= pd.Timestamp(start_date)]
        if end_date:
            close = close[close.index <= pd.Timestamp(end_date)]

        if close.empty:
            raise ValueError("No price data in the specified range")

        if total_budget is None:
            total_budget = sum(gl.budget_allocation for gl in grid_levels)

        spacing_pct = abs(grid_levels[0].drop_pct) if grid_levels else 5.0
        num_levels = len(grid_levels)

        # ── DCA 기본 금액: 예산을 기간에 걸쳐 분배 ──
        total_weeks = max(1, len(close) // 5)
        base_dca = total_budget / total_weeks  # 주당 기본 매수액

        # ── 상태 ──
        remaining_budget = total_budget
        shares_held = 0
        avg_cost = 0.0
        trades: list[BacktestTrade] = []
        equity_data: list[dict] = []
        max_unrealized_loss_pct = 0.0

        seed_buy_done = False
        prev_regime = ""
        regime_changes = 0
        seed_buy_count = 0
        idle_dca_count = 0
        last_dca_idx = -999

        close_values = close.values
        close_index = close.index

        # ATH 추적 (rolling)
        running_ath = float(close_values[0])

        for i in range(len(close_values)):
            date = close_index[i]
            price = float(close_values[i])
            regime = detect_regime(close, i)

            if regime != prev_regime and prev_regime:
                regime_changes += 1
            prev_regime = regime

            # ATH 업데이트
            if price > running_ath:
                running_ath = price

            # 현재 낙폭
            dd_pct = (price - running_ath) / running_ath * 100 if running_ath > 0 else 0
            dd_mult = self._get_dd_multiplier(dd_pct)

            # ── 1. 시드 매수 (상승장 진입, 보유분 없을 때) ──
            if (regime in ("BULL", "BULL_STRONG")
                    and shares_held == 0
                    and not seed_buy_done
                    and remaining_budget > 0):
                seed_amount = min(remaining_budget * 0.30, remaining_budget)
                seed_qty = math.floor(seed_amount / price)
                if seed_qty > 0:
                    cost = seed_qty * price
                    shares_held = seed_qty
                    avg_cost = price
                    remaining_budget -= cost
                    seed_buy_done = True
                    seed_buy_count += 1

                    trades.append(BacktestTrade(
                        date=date, action="SEED_BUY", price=round(price, 2),
                        quantity=seed_qty, grid_level=0,
                        cost_basis=round(price, 2),
                        regime=regime,
                        note=f"seed 30% entry",
                    ))

            # ── 2. 주간 DCA (낙폭 배수 적용) ──
            # 매주 1회 (5거래일 간격), 낙폭 깊을수록 더 많이 매수
            if (i - last_dca_idx >= 5 and i > 0
                    and remaining_budget > total_budget * 0.02):
                dca_amount = min(base_dca * dd_mult, remaining_budget)
                dca_qty = math.floor(dca_amount / price)
                if dca_qty > 0:
                    cost = dca_qty * price
                    total_cost_before = shares_held * avg_cost
                    shares_held += dca_qty
                    avg_cost = (total_cost_before + cost) / shares_held if shares_held > 0 else price
                    remaining_budget -= cost
                    idle_dca_count += 1
                    last_dca_idx = i

                    dd_label = f"dd {dd_pct:.0f}% x{dd_mult:.1f}"
                    trades.append(BacktestTrade(
                        date=date, action="DCA", price=round(price, 2),
                        quantity=dca_qty, grid_level=0,
                        cost_basis=round(avg_cost, 2),
                        regime=regime,
                        note=dd_label,
                    ))

            # ── MDD 추적 ──
            if shares_held > 0 and avg_cost > 0:
                unrealized_pct = (price - avg_cost) / avg_cost * 100
                max_unrealized_loss_pct = min(max_unrealized_loss_pct, unrealized_pct)

            # ── 기록 ──
            equity = remaining_budget + (shares_held * price)
            invested = total_budget - remaining_budget
            equity_data.append({
                "date": date,
                "equity": round(equity, 2),
                "invested": round(invested, 2) if shares_held > 0 else 0,
                "shares": shares_held,
                "avg_cost": round(avg_cost, 2),
                "price": round(price, 2),
                "regime": regime,
            })

        # ── 요약 ──
        equity_df = pd.DataFrame(equity_data)
        if equity_df.empty:
            raise ValueError("No equity data generated")

        equity_df.set_index("date", inplace=True)

        final_equity = equity_df["equity"].iloc[-1]
        total_return = (final_equity - total_budget) / total_budget * 100

        days = (close.index[-1] - close.index[0]).days
        years = max(days / 365.25, 0.01)
        annualized = ((final_equity / total_budget) ** (1 / years) - 1) * 100

        eq_series = equity_df["equity"]
        eq_cummax = eq_series.cummax()
        eq_dd = ((eq_series - eq_cummax) / eq_cummax * 100)
        max_dd = float(eq_dd.min())

        num_buys = sum(1 for t in trades if t.action in ("DCA", "SEED_BUY"))

        leverage_decay = self._estimate_leverage_decay(close, equity_df)

        return BacktestResult(
            start_date=close.index[0],
            end_date=close.index[-1],
            ticker=ticker,
            total_budget=total_budget,
            final_value=round(final_equity, 2),
            total_return_pct=round(total_return, 2),
            annualized_return_pct=round(annualized, 2),
            max_drawdown_pct=round(max_dd, 2),
            max_unrealized_loss_pct=round(max_unrealized_loss_pct, 2),
            num_buys=num_buys,
            num_sells=0,
            num_rounds=1,
            total_realized_pnl=0.0,
            win_rate=0.0,
            avg_cost_basis=round(avg_cost, 2),
            trades=trades,
            equity_curve=equity_df,
            grid_config={
                "num_levels": num_levels,
                "spacing_pct": spacing_pct,
            },
            seed_buys=seed_buy_count,
            rebalances=0,
            regime_changes=regime_changes,
            leverage_decay_pct=round(leverage_decay, 2),
            idle_dca_buys=idle_dca_count,
            upside_buys=0,
        )

    def _estimate_leverage_decay(self, close: pd.Series, equity_df: pd.DataFrame) -> float:
        """레버리지 디케이 추정 (횡보 구간에서의 가치 침식).

        시작/끝 가격이 비슷한데 중간 변동이 크면 디케이 발생.
        """
        if len(close) < 60:
            return 0.0

        start_price = float(close.iloc[0])
        end_price = float(close.iloc[-1])
        price_change = (end_price - start_price) / start_price * 100

        # 일간 변동성의 누적 효과
        daily_returns = close.pct_change().dropna()
        vol = float(daily_returns.std())

        # 레버리지 디케이 ≈ -0.5 * leverage^2 * variance * days
        # 3x ETF 가정
        days = len(daily_returns)
        theoretical_decay = -0.5 * 9 * (vol ** 2) * days * 100  # %

        return theoretical_decay

    def run_comparison_backtest(
        self,
        df: pd.DataFrame,
        grid_levels: list[GridLevel],
        ticker: str = "",
        start_date: str = None,
        end_date: str = None,
        profit_target_pct: float = 10.0,
    ) -> dict:
        """그리드(적응형) vs 일시투자 vs DCA 비교."""
        close = df["Close"].dropna()
        if start_date:
            close = close[close.index >= pd.Timestamp(start_date)]
        if end_date:
            close = close[close.index <= pd.Timestamp(end_date)]

        total_budget = sum(gl.budget_allocation for gl in grid_levels)

        # 1. Adaptive Grid
        grid_result = self.run_backtest(
            df, grid_levels, ticker, start_date, end_date,
            profit_target_pct, reinvest_profits=True, total_budget=total_budget,
        )

        # 2. Lump sum
        start_price = float(close.iloc[0])
        lump_shares = math.floor(total_budget / start_price)
        lump_equity = []
        for date, price in close.items():
            eq = (total_budget - lump_shares * start_price) + lump_shares * float(price)
            lump_equity.append({"date": date, "equity": round(eq, 2)})
        lump_df = pd.DataFrame(lump_equity).set_index("date")
        lump_final = lump_df["equity"].iloc[-1]
        lump_return = (lump_final - total_budget) / total_budget * 100

        # Lump sum MDD
        lump_eq = lump_df["equity"]
        lump_cummax = lump_eq.cummax()
        lump_dd = ((lump_eq - lump_cummax) / lump_cummax * 100)
        lump_mdd = float(lump_dd.min())

        # 3. Monthly DCA
        monthly_budget = total_budget / max(1, len(close.resample("ME").last()))
        dca_shares = 0
        dca_remaining = total_budget
        dca_equity = []
        monthly_dates = close.resample("ME").last().index

        for date, price in close.items():
            p = float(price)
            if date in monthly_dates and dca_remaining >= monthly_budget:
                buy_qty = math.floor(monthly_budget / p)
                if buy_qty > 0:
                    cost = buy_qty * p
                    dca_shares += buy_qty
                    dca_remaining -= cost

            eq = dca_remaining + dca_shares * p
            dca_equity.append({"date": date, "equity": round(eq, 2)})

        dca_df = pd.DataFrame(dca_equity).set_index("date")
        dca_final = dca_df["equity"].iloc[-1]
        dca_return = (dca_final - total_budget) / total_budget * 100

        return {
            "grid": {
                "final_value": grid_result.final_value,
                "total_return_pct": grid_result.total_return_pct,
                "max_drawdown_pct": grid_result.max_drawdown_pct,
                "num_trades": grid_result.num_buys,
                "equity_curve": grid_result.equity_curve,
                "seed_buys": grid_result.seed_buys,
                "rebalances": grid_result.rebalances,
                "idle_dca_buys": grid_result.idle_dca_buys,
            },
            "lump_sum": {
                "final_value": round(lump_final, 2),
                "total_return_pct": round(lump_return, 2),
                "max_drawdown_pct": round(lump_mdd, 2),
                "equity_curve": lump_df,
            },
            "dca": {
                "final_value": round(dca_final, 2),
                "total_return_pct": round(dca_return, 2),
                "equity_curve": dca_df,
            },
            "total_budget": total_budget,
            "period": f"{close.index[0].date()} ~ {close.index[-1].date()}",
        }

    def run_crash_scenario(
        self,
        df: pd.DataFrame,
        grid_levels: list[GridLevel],
        ticker: str = "",
        crash_periods: list[dict] = None,
        profit_target_pct: float = 10.0,
    ) -> list[dict]:
        """위기 구간 백테스트 (구간별 시작가 기준 그리드 자동 재설정)."""
        if crash_periods is None:
            crash_periods = [
                {"name": "COVID-19", "start": "2020-02-19", "end": "2020-08-18"},
                {"name": "2022 Bear Market", "start": "2021-12-27", "end": "2023-06-01"},
                {"name": "Q4 2018", "start": "2018-10-01", "end": "2019-06-01"},
            ]

        spacing_pct = abs(grid_levels[0].drop_pct) if grid_levels else 5.0
        num_levels = len(grid_levels)
        total_budget = sum(gl.budget_allocation for gl in grid_levels)

        results = []
        for period in crash_periods:
            try:
                # 구간 시작가 기준으로 그리드 재설정
                close = df["Close"].dropna()
                mask = close.index >= pd.Timestamp(period["start"])
                if mask.any():
                    ref_price = float(close[mask].iloc[0])
                else:
                    raise ValueError("No data for period start")

                period_grid = GridCalculator().calculate_grid(
                    reference_price=ref_price,
                    total_budget=total_budget,
                    num_levels=num_levels,
                    spacing_pct=spacing_pct,
                    weighting="equal",
                )

                result = self.run_backtest(
                    df, period_grid, ticker,
                    start_date=period["start"],
                    end_date=period["end"],
                    profit_target_pct=profit_target_pct,
                    reinvest_profits=True,
                    total_budget=total_budget,
                )
                results.append({
                    "period_name": period["name"],
                    "start": period["start"],
                    "end": period["end"],
                    "result": result,
                })
            except (ValueError, Exception) as e:
                logger.warning(f"Could not run crash scenario {period['name']}: {e}")
                results.append({
                    "period_name": period["name"],
                    "start": period["start"],
                    "end": period["end"],
                    "result": None,
                    "error": str(e),
                })

        return results
