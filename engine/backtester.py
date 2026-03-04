import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from engine.grid_calculator import GridCalculator, GridLevel

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Single trade in backtest."""
    date: datetime
    action: str  # "BUY" or "SELL"
    price: float
    quantity: int
    grid_level: int
    cost_basis: float
    pnl: float = 0.0
    round_number: int = 1


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


class GridBacktester:
    """Backtest grid buying strategy on historical data."""

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
        """Simulate grid buying strategy on historical price data."""
        close = df["Close"].dropna()

        if start_date:
            close = close[close.index >= pd.Timestamp(start_date)]
        if end_date:
            close = close[close.index <= pd.Timestamp(end_date)]

        if close.empty:
            raise ValueError("No price data in the specified range")

        if total_budget is None:
            total_budget = sum(gl.budget_allocation for gl in grid_levels)

        # State
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

        # Current grid reference price for recalculation
        current_grid = list(grid_levels)

        for date, price_val in close.items():
            price = float(price_val)

            # Check buy triggers
            for gl in current_grid:
                if gl.level_number in filled_levels:
                    continue
                if price <= gl.target_price:
                    buy_qty = gl.quantity
                    cost = buy_qty * price
                    if cost > remaining_budget:
                        buy_qty = math.floor(remaining_budget / price)
                        cost = buy_qty * price

                    if buy_qty > 0:
                        total_cost_before = shares_held * avg_cost
                        shares_held += buy_qty
                        avg_cost = (total_cost_before + cost) / shares_held
                        remaining_budget -= cost
                        filled_levels.add(gl.level_number)

                        trades.append(BacktestTrade(
                            date=date,
                            action="BUY",
                            price=round(price, 2),
                            quantity=buy_qty,
                            grid_level=gl.level_number,
                            cost_basis=round(avg_cost, 2),
                            round_number=round_number,
                        ))

            # Check profit target
            if shares_held > 0:
                current_pnl_pct = (price - avg_cost) / avg_cost * 100
                unrealized_loss = min(0, current_pnl_pct)
                max_unrealized_loss_pct = min(max_unrealized_loss_pct, unrealized_loss)

                if current_pnl_pct >= profit_target_pct:
                    sell_value = shares_held * price
                    realized_pnl = sell_value - (shares_held * avg_cost)
                    total_realized_pnl += realized_pnl
                    sell_count += 1
                    if realized_pnl > 0:
                        sell_wins += 1

                    trades.append(BacktestTrade(
                        date=date,
                        action="SELL",
                        price=round(price, 2),
                        quantity=shares_held,
                        grid_level=0,
                        cost_basis=round(avg_cost, 2),
                        pnl=round(realized_pnl, 2),
                        round_number=round_number,
                    ))

                    if reinvest_profits:
                        remaining_budget += sell_value
                        shares_held = 0
                        avg_cost = 0.0
                        filled_levels = set()
                        round_number += 1

                        # Recalculate grid from current price
                        calc = GridCalculator()
                        spacing = grid_levels[0].drop_pct if grid_levels else -5.0
                        current_grid = calc.calculate_grid(
                            reference_price=price,
                            total_budget=remaining_budget,
                            num_levels=len(grid_levels),
                            spacing_pct=abs(spacing),
                            weighting="linear",
                        )
                    else:
                        remaining_budget += sell_value
                        shares_held = 0
                        avg_cost = 0.0

            # Record equity
            equity = remaining_budget + (shares_held * price)
            invested = total_budget - remaining_budget
            equity_data.append({
                "date": date,
                "equity": round(equity, 2),
                "invested": round(invested, 2) if shares_held > 0 else 0,
                "shares": shares_held,
                "avg_cost": round(avg_cost, 2),
                "price": round(price, 2),
            })

        # Summary
        equity_df = pd.DataFrame(equity_data)
        if equity_df.empty:
            raise ValueError("No equity data generated")

        equity_df.set_index("date", inplace=True)

        final_equity = equity_df["equity"].iloc[-1]
        total_return = (final_equity - total_budget) / total_budget * 100

        days = (close.index[-1] - close.index[0]).days
        years = max(days / 365.25, 0.01)
        annualized = ((final_equity / total_budget) ** (1 / years) - 1) * 100

        # Max drawdown of equity curve
        eq_series = equity_df["equity"]
        eq_cummax = eq_series.cummax()
        eq_dd = ((eq_series - eq_cummax) / eq_cummax * 100)
        max_dd = float(eq_dd.min())

        num_buys = sum(1 for t in trades if t.action == "BUY")
        win_rate = (sell_wins / sell_count * 100) if sell_count > 0 else 0

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
                "num_levels": len(grid_levels),
                "spacing_pct": abs(grid_levels[0].drop_pct) if grid_levels else 5.0,
            },
        )

    def run_comparison_backtest(
        self,
        df: pd.DataFrame,
        grid_levels: list[GridLevel],
        ticker: str = "",
        start_date: str = None,
        end_date: str = None,
        profit_target_pct: float = 10.0,
    ) -> dict:
        """Compare grid strategy vs alternatives."""
        close = df["Close"].dropna()
        if start_date:
            close = close[close.index >= pd.Timestamp(start_date)]
        if end_date:
            close = close[close.index <= pd.Timestamp(end_date)]

        total_budget = sum(gl.budget_allocation for gl in grid_levels)

        # 1. Grid strategy
        grid_result = self.run_backtest(
            df, grid_levels, ticker, start_date, end_date,
            profit_target_pct, reinvest_profits=True, total_budget=total_budget,
        )

        # 2. Lump sum - buy everything at start
        start_price = float(close.iloc[0])
        lump_shares = math.floor(total_budget / start_price)
        lump_equity = []
        for date, price in close.items():
            eq = (total_budget - lump_shares * start_price) + lump_shares * float(price)
            lump_equity.append({"date": date, "equity": round(eq, 2)})
        lump_df = pd.DataFrame(lump_equity).set_index("date")
        lump_final = lump_df["equity"].iloc[-1]
        lump_return = (lump_final - total_budget) / total_budget * 100

        # 3. Simple DCA - equal monthly buys
        monthly_budget = total_budget / max(1, len(close.resample("ME").last()))
        dca_shares = 0
        dca_spent = 0.0
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
                    dca_spent += cost
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
            },
            "lump_sum": {
                "final_value": round(lump_final, 2),
                "total_return_pct": round(lump_return, 2),
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
        """Run backtest specifically during known crash periods."""
        if crash_periods is None:
            crash_periods = [
                {"name": "COVID-19", "start": "2020-02-19", "end": "2020-08-18"},
                {"name": "2022 Bear Market", "start": "2021-12-27", "end": "2023-01-19"},
                {"name": "Q4 2018", "start": "2018-10-01", "end": "2019-04-01"},
            ]

        results = []
        for period in crash_periods:
            try:
                result = self.run_backtest(
                    df, grid_levels, ticker,
                    start_date=period["start"],
                    end_date=period["end"],
                    profit_target_pct=profit_target_pct,
                    reinvest_profits=True,
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
