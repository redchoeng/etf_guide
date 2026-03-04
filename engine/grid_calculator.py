import math
from dataclasses import dataclass, field


@dataclass
class GridLevel:
    """Single grid level definition."""
    level_number: int
    drop_pct: float
    target_price: float
    budget_allocation: float
    budget_pct: float
    quantity: int
    cumulative_budget: float = 0.0
    cumulative_shares: int = 0
    avg_cost_basis: float = 0.0


class GridCalculator:
    """Grid buying level calculator with pyramid weighting."""

    WEIGHTING_METHODS = {
        "equal": "Equal weight across all levels",
        "linear": "Linearly increasing (2x at bottom vs top)",
        "exponential": "Exponentially increasing (heavier at deeper drops)",
        "fibonacci": "Fibonacci-ratio weighting",
    }

    def __init__(self, config: dict = None):
        config = config or {}
        self.default_levels = config.get("default_levels", 10)
        self.default_spacing_pct = config.get("default_spacing_pct", 5.0)
        self.default_weighting = config.get("default_weighting", "linear")

    def calculate_grid(
        self,
        reference_price: float,
        total_budget: float,
        num_levels: int = 10,
        spacing_pct: float = 5.0,
        weighting: str = "linear",
        custom_weights: list[float] = None,
    ) -> list[GridLevel]:
        """Calculate grid levels with pyramid weighting.

        Args:
            reference_price: Price to calculate drops from (ATH or current).
            total_budget: Total USD budget to allocate.
            num_levels: Number of grid levels.
            spacing_pct: Percentage between each level.
            weighting: Weight method (equal/linear/exponential/fibonacci).
            custom_weights: Custom weights per level (overrides weighting).

        Returns:
            List of GridLevel objects.
        """
        if num_levels < 1:
            raise ValueError("num_levels must be >= 1")
        if total_budget <= 0:
            raise ValueError("total_budget must be > 0")
        if reference_price <= 0:
            raise ValueError("reference_price must be > 0")

        # Step 1: Calculate target prices
        target_prices = []
        for i in range(1, num_levels + 1):
            drop = spacing_pct * i
            price = reference_price * (1 - drop / 100)
            if price <= 0:
                break
            target_prices.append((i, -drop, price))

        actual_levels = len(target_prices)

        # Step 2: Calculate weights
        if custom_weights and len(custom_weights) >= actual_levels:
            raw_weights = custom_weights[:actual_levels]
        else:
            raw_weights = self._get_weights(actual_levels, weighting)

        total_weight = sum(raw_weights)
        norm_weights = [w / total_weight for w in raw_weights]

        # Step 3: Allocate budget and calculate quantities
        levels = []
        cum_budget = 0.0
        cum_shares = 0

        for idx, (level_num, drop_pct, target_price) in enumerate(target_prices):
            budget = total_budget * norm_weights[idx]
            qty = math.floor(budget / target_price)
            actual_cost = qty * target_price

            cum_budget += actual_cost
            cum_shares += qty
            avg_cost = cum_budget / cum_shares if cum_shares > 0 else 0

            levels.append(GridLevel(
                level_number=level_num,
                drop_pct=drop_pct,
                target_price=round(target_price, 2),
                budget_allocation=round(budget, 2),
                budget_pct=round(norm_weights[idx] * 100, 2),
                quantity=qty,
                cumulative_budget=round(cum_budget, 2),
                cumulative_shares=cum_shares,
                avg_cost_basis=round(avg_cost, 2),
            ))

        return levels

    def calculate_grid_from_drawdown(
        self,
        current_price: float,
        max_historical_drawdown: float,
        total_budget: float,
        num_levels: int = 10,
        weighting: str = "linear",
        coverage_pct: float = 80.0,
    ) -> list[GridLevel]:
        """Auto-calculate grid spacing based on historical max drawdown.

        Args:
            current_price: Current ETF price.
            max_historical_drawdown: Historical max drawdown as negative % (e.g., -79.5).
            total_budget: Total budget.
            num_levels: Number of levels.
            weighting: Weighting method.
            coverage_pct: Percentage of max drawdown to cover (0-100).

        Returns:
            List of GridLevel objects.
        """
        dd_abs = abs(max_historical_drawdown)
        effective_dd = dd_abs * (coverage_pct / 100)
        spacing = effective_dd / num_levels

        return self.calculate_grid(
            reference_price=current_price,
            total_budget=total_budget,
            num_levels=num_levels,
            spacing_pct=spacing,
            weighting=weighting,
        )

    def calculate_recovery_targets(
        self,
        grid_levels: list[GridLevel],
        target_profit_pct: float = 10.0,
    ) -> list[dict]:
        """For each fill scenario, calculate the price needed for target profit.

        Returns:
            List of dicts with levels_filled, avg_cost, target_sell_price, etc.
        """
        results = []
        cum_cost = 0.0
        cum_shares = 0

        for level in grid_levels:
            cum_cost += level.quantity * level.target_price
            cum_shares += level.quantity

            if cum_shares == 0:
                continue

            avg_cost = cum_cost / cum_shares
            target_sell = avg_cost * (1 + target_profit_pct / 100)
            projected_profit = cum_shares * (target_sell - avg_cost)

            results.append({
                "levels_filled": level.level_number,
                "avg_cost": round(avg_cost, 2),
                "target_sell_price": round(target_sell, 2),
                "total_invested": round(cum_cost, 2),
                "total_shares": cum_shares,
                "projected_profit": round(projected_profit, 2),
                "profit_pct": target_profit_pct,
            })

        return results

    def _get_weights(self, n: int, method: str) -> list[float]:
        if method == "equal":
            return [1.0] * n
        elif method == "linear":
            return [float(i) for i in range(1, n + 1)]
        elif method == "exponential":
            return [2.0 ** i for i in range(n)]
        elif method == "fibonacci":
            return self._fibonacci_weights(n)
        else:
            return [1.0] * n

    @staticmethod
    def _fibonacci_weights(n: int) -> list[float]:
        if n <= 0:
            return []
        fibs = [1.0, 1.0]
        while len(fibs) < n:
            fibs.append(fibs[-1] + fibs[-2])
        return fibs[:n]
