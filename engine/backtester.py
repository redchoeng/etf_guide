"""적응형 그리드 백테스터.

레짐(상승/하락/횡보) 감지 → 동적 투자비율, 시드매수, 부분익절, 트레일링 스탑,
그리드 리밸런싱, 레버리지 디케이 경고를 반영한 백테스트 엔진.

v2 개선사항:
  1. 상승장 시드매수: 추세 진입 시 즉시 30% 초기 매수
  2. 레짐별 투자비율: BULL 75% → BEAR 45%
  3. 부분익절: 상승장에서 1/3씩 3단계 익절
  4. 트레일링 스탑: 고점 대비 -7% 하락 시 잔여 전량 청산
  5. 그리드 리밸런싱: 가격이 그리드 상단 15% 이상 벗어나면 재설정
  6. 레버리지 디케이 추적: 횡보장 3x ETF 손실 추적
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
    action: str  # BUY, SEED_BUY, SELL, SELL_PARTIAL, SELL_TRAILING, REBALANCE
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
    # v2 추가 필드
    seed_buys: int = 0
    partial_sells: int = 0
    trailing_stops: int = 0
    rebalances: int = 0
    regime_changes: int = 0
    leverage_decay_pct: float = 0.0


# ── 레짐별 설정 ──────────────────────────────────────────

REGIME_ALLOCATION = {
    "BULL_STRONG": 0.75,
    "BULL":        0.70,
    "SIDEWAYS":    0.55,
    "CORRECTION":  0.50,
    "BEAR":        0.45,
    "CRISIS":      0.40,
}

# 부분익절 목표 (단계별 %)
REGIME_PROFIT_TARGETS = {
    "BULL_STRONG": [15, 25, 40],   # 1/3 @ 15%, 1/3 @ 25%, 나머지 트레일링
    "BULL":        [12, 22, 35],
    "SIDEWAYS":    [8, 15],        # 1/2 @ 8%, 나머지 @ 15%
    "CORRECTION":  [10],           # 전량 @ 10%
    "BEAR":        [10],
    "CRISIS":      [8],
}

# 트레일링 스탑 (고점 대비 하락 %)
REGIME_TRAILING_STOP = {
    "BULL_STRONG": 7.0,
    "BULL":        7.0,
    "SIDEWAYS":    5.0,
    "CORRECTION":  5.0,
    "BEAR":        5.0,
    "CRISIS":      4.0,
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
    """적응형 그리드 백테스터.

    상승장: 시드매수 → 눌림목 그리드 추가매수 → 부분익절 → 트레일링 스탑
    하락장: 그리드 분할매수 → 목표가 전량 익절 → 재투자
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.profit_target_pct = config.get("profit_target_pct", 10.0)

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
        """적응형 그리드 백테스트 실행."""
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

        # ── 상태 ──
        remaining_budget = total_budget
        shares_held = 0
        avg_cost = 0.0
        filled_levels: set[int] = set()
        trades: list[BacktestTrade] = []
        equity_data: list[dict] = []
        round_number = 1
        total_realized_pnl = 0.0
        sell_wins = 0
        sell_count = 0
        max_unrealized_loss_pct = 0.0

        current_grid = list(grid_levels)
        grid_ref_price = grid_levels[0].target_price / (1 - abs(grid_levels[0].drop_pct) / 100) if grid_levels else float(close.iloc[0])

        # v2 상태
        seed_buy_done = False
        partial_sells_done = 0  # 현재 라운드에서 부분 익절 횟수
        peak_price = 0.0        # 매수 후 고점 (트레일링 스탑용)
        last_rebalance_idx = -999
        prev_regime = ""
        regime_changes = 0
        seed_buy_count = 0
        partial_sell_count = 0
        trailing_stop_count = 0
        rebalance_count = 0

        close_values = close.values
        close_index = close.index

        for i in range(len(close_values)):
            date = close_index[i]
            price = float(close_values[i])
            regime = detect_regime(close, i)

            if regime != prev_regime and prev_regime:
                regime_changes += 1
            prev_regime = regime

            allocation = REGIME_ALLOCATION.get(regime, 0.55)
            investable_limit = total_budget * allocation

            # ── 1. 시드 매수 (상승장 진입) ──
            if (regime in ("BULL", "BULL_STRONG")
                    and shares_held == 0
                    and not seed_buy_done):
                seed_amount = min(
                    investable_limit * 0.30,  # 투자가능액의 30%
                    remaining_budget,
                )
                seed_qty = math.floor(seed_amount / price)
                if seed_qty > 0:
                    cost = seed_qty * price
                    shares_held = seed_qty
                    avg_cost = price
                    remaining_budget -= cost
                    seed_buy_done = True
                    peak_price = price
                    seed_buy_count += 1

                    trades.append(BacktestTrade(
                        date=date, action="SEED_BUY", price=round(price, 2),
                        quantity=seed_qty, grid_level=0,
                        cost_basis=round(price, 2),
                        round_number=round_number, regime=regime,
                        note=f"seed {allocation:.0%} alloc",
                    ))

            # ── 2. 그리드 매수 ──
            invested_amount = total_budget - remaining_budget
            for gl in current_grid:
                if gl.level_number in filled_levels:
                    continue
                if price <= gl.target_price:
                    buy_qty = gl.quantity
                    cost = buy_qty * price

                    # 투자 한도 체크
                    if invested_amount + cost > investable_limit:
                        allowed = investable_limit - invested_amount
                        if allowed <= 0:
                            break
                        buy_qty = math.floor(allowed / price)
                        cost = buy_qty * price

                    if cost > remaining_budget:
                        buy_qty = math.floor(remaining_budget / price)
                        cost = buy_qty * price

                    if buy_qty > 0:
                        total_cost_before = shares_held * avg_cost
                        shares_held += buy_qty
                        avg_cost = (total_cost_before + cost) / shares_held
                        remaining_budget -= cost
                        invested_amount += cost
                        filled_levels.add(gl.level_number)
                        if peak_price == 0:
                            peak_price = price

                        trades.append(BacktestTrade(
                            date=date, action="BUY", price=round(price, 2),
                            quantity=buy_qty, grid_level=gl.level_number,
                            cost_basis=round(avg_cost, 2),
                            round_number=round_number, regime=regime,
                        ))

            # ── 3. 익절 / 트레일링 스탑 ──
            if shares_held > 0:
                profit_pct = (price - avg_cost) / avg_cost * 100
                unrealized_loss = min(0, profit_pct)
                max_unrealized_loss_pct = min(max_unrealized_loss_pct, unrealized_loss)
                peak_price = max(peak_price, price)

                targets = REGIME_PROFIT_TARGETS.get(regime, [10])
                trailing_stop_pct = REGIME_TRAILING_STOP.get(regime, 5.0)

                sold_this_bar = False

                # 부분 익절 (상승장: 3단계, 횡보장: 2단계)
                if len(targets) >= 2 and partial_sells_done < len(targets) - 1:
                    target = targets[partial_sells_done]
                    if profit_pct >= target:
                        sell_portion = len(targets) - partial_sells_done
                        sell_qty = max(1, shares_held // sell_portion)

                        if sell_qty > 0 and sell_qty < shares_held:
                            sell_value = sell_qty * price
                            realized = sell_qty * (price - avg_cost)
                            total_realized_pnl += realized
                            shares_held -= sell_qty
                            remaining_budget += sell_value
                            partial_sells_done += 1
                            partial_sell_count += 1
                            sell_count += 1
                            if realized > 0:
                                sell_wins += 1

                            trades.append(BacktestTrade(
                                date=date, action="SELL_PARTIAL",
                                price=round(price, 2), quantity=sell_qty,
                                grid_level=0, cost_basis=round(avg_cost, 2),
                                pnl=round(realized, 2),
                                round_number=round_number, regime=regime,
                                note=f"stage {partial_sells_done}/{len(targets)-1} @ {target}%",
                            ))
                            sold_this_bar = True

                # 트레일링 스탑 (수익 상태에서만 발동)
                if not sold_this_bar and shares_held > 0 and profit_pct > 0:
                    trail_dd = (price - peak_price) / peak_price * 100
                    # 최소 수익 확보 후 트레일링 발동
                    min_profit_for_trail = targets[-1] * 0.4 if targets else 4.0
                    if profit_pct >= min_profit_for_trail and trail_dd <= -trailing_stop_pct:
                        sell_value = shares_held * price
                        realized = sell_value - (shares_held * avg_cost)
                        total_realized_pnl += realized
                        sell_count += 1
                        trailing_stop_count += 1
                        if realized > 0:
                            sell_wins += 1

                        trades.append(BacktestTrade(
                            date=date, action="SELL_TRAILING",
                            price=round(price, 2), quantity=shares_held,
                            grid_level=0, cost_basis=round(avg_cost, 2),
                            pnl=round(realized, 2),
                            round_number=round_number, regime=regime,
                            note=f"trail {trail_dd:.1f}% from peak ${peak_price:.2f}",
                        ))

                        if reinvest_profits:
                            remaining_budget += sell_value
                            shares_held = 0
                            avg_cost = 0.0
                            filled_levels = set()
                            partial_sells_done = 0
                            peak_price = 0.0
                            seed_buy_done = False
                            round_number += 1

                            current_grid = GridCalculator().calculate_grid(
                                reference_price=price,
                                total_budget=remaining_budget * allocation,
                                num_levels=num_levels,
                                spacing_pct=spacing_pct,
                                weighting="linear",
                            )
                            grid_ref_price = price
                        else:
                            remaining_budget += sell_value
                            shares_held = 0
                            avg_cost = 0.0
                        sold_this_bar = True

                # 고정 목표 익절 (하락장/위기 - 전량)
                if not sold_this_bar and shares_held > 0 and len(targets) == 1:
                    if profit_pct >= targets[0]:
                        sell_value = shares_held * price
                        realized = sell_value - (shares_held * avg_cost)
                        total_realized_pnl += realized
                        sell_count += 1
                        if realized > 0:
                            sell_wins += 1

                        trades.append(BacktestTrade(
                            date=date, action="SELL",
                            price=round(price, 2), quantity=shares_held,
                            grid_level=0, cost_basis=round(avg_cost, 2),
                            pnl=round(realized, 2),
                            round_number=round_number, regime=regime,
                        ))

                        if reinvest_profits:
                            remaining_budget += sell_value
                            shares_held = 0
                            avg_cost = 0.0
                            filled_levels = set()
                            partial_sells_done = 0
                            peak_price = 0.0
                            seed_buy_done = False
                            round_number += 1

                            current_grid = GridCalculator().calculate_grid(
                                reference_price=price,
                                total_budget=remaining_budget * allocation,
                                num_levels=num_levels,
                                spacing_pct=spacing_pct,
                                weighting="linear",
                            )
                            grid_ref_price = price
                        else:
                            remaining_budget += sell_value
                            shares_held = 0
                            avg_cost = 0.0
                        sold_this_bar = True

            # ── 4. 그리드 리밸런싱 ──
            if (not sold_this_bar if shares_held > 0 else True):
                if i - last_rebalance_idx >= 22 and current_grid:  # ~1개월
                    top_price = current_grid[0].target_price
                    if price > top_price * 1.15:
                        # 가격이 그리드 상단 15% 이상 벗어남 → 재설정
                        alloc_budget = (total_budget - (shares_held * avg_cost if shares_held else 0))
                        alloc_budget = max(alloc_budget, remaining_budget) * allocation
                        if alloc_budget > 0:
                            current_grid = GridCalculator().calculate_grid(
                                reference_price=price,
                                total_budget=alloc_budget,
                                num_levels=num_levels,
                                spacing_pct=spacing_pct,
                                weighting="linear",
                            )
                            filled_levels = set()
                            grid_ref_price = price
                            last_rebalance_idx = i
                            rebalance_count += 1

                            trades.append(BacktestTrade(
                                date=date, action="REBALANCE",
                                price=round(price, 2), quantity=0,
                                grid_level=0, cost_basis=0,
                                round_number=round_number, regime=regime,
                                note=f"grid reset from ${top_price:.2f}",
                            ))

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

        num_buys = sum(1 for t in trades if t.action in ("BUY", "SEED_BUY"))
        win_rate = (sell_wins / sell_count * 100) if sell_count > 0 else 0

        # 레버리지 디케이 추적 (3x ETF 횡보 구간)
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
            num_sells=sell_count,
            num_rounds=round_number,
            total_realized_pnl=round(total_realized_pnl, 2),
            win_rate=round(win_rate, 2),
            avg_cost_basis=round(avg_cost, 2),
            trades=trades,
            equity_curve=equity_df,
            grid_config={
                "num_levels": num_levels,
                "spacing_pct": spacing_pct,
            },
            seed_buys=seed_buy_count,
            partial_sells=partial_sell_count,
            trailing_stops=trailing_stop_count,
            rebalances=rebalance_count,
            regime_changes=regime_changes,
            leverage_decay_pct=round(leverage_decay, 2),
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
                "num_trades": grid_result.num_buys + grid_result.num_sells,
                "equity_curve": grid_result.equity_curve,
                "seed_buys": grid_result.seed_buys,
                "partial_sells": grid_result.partial_sells,
                "trailing_stops": grid_result.trailing_stops,
                "rebalances": grid_result.rebalances,
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
                    weighting="linear",
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
