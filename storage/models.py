from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, Float, String, Boolean, Text, DateTime, JSON,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ETFConfig(Base):
    """User-configured ETF with grid parameters."""
    __tablename__ = "etf_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), unique=True, index=True)
    name = Column(String(100))
    underlying_ticker = Column(String(10))
    leverage_factor = Column(Integer, default=2)
    total_budget = Column(Float)
    num_levels = Column(Integer, default=10)
    spacing_pct = Column(Float, default=5.0)
    weighting_method = Column(String(20), default="linear")
    reference_price = Column(Float)
    profit_target_pct = Column(Float, default=10.0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    grid_levels = relationship(
        "GridLevelRecord", back_populates="etf_config",
        cascade="all, delete-orphan",
    )
    purchases = relationship(
        "PurchaseRecord", back_populates="etf_config",
        cascade="all, delete-orphan",
    )


class GridLevelRecord(Base):
    """Calculated grid level for an ETF."""
    __tablename__ = "grid_levels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    etf_config_id = Column(Integer, ForeignKey("etf_configs.id"), index=True)
    level_number = Column(Integer)
    drop_pct = Column(Float)
    target_price = Column(Float)
    budget_allocation = Column(Float)
    budget_pct = Column(Float)
    target_quantity = Column(Integer)
    is_filled = Column(Boolean, default=False)
    filled_date = Column(DateTime, nullable=True)
    filled_price = Column(Float, nullable=True)
    filled_quantity = Column(Integer, nullable=True)

    etf_config = relationship("ETFConfig", back_populates="grid_levels")


class PurchaseRecord(Base):
    """Actual purchase record for portfolio tracking."""
    __tablename__ = "purchase_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    etf_config_id = Column(Integer, ForeignKey("etf_configs.id"), index=True)
    ticker = Column(String(10), index=True)
    purchase_date = Column(DateTime, index=True)
    price = Column(Float)
    quantity = Column(Integer)
    total_cost = Column(Float)
    grid_level = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    etf_config = relationship("ETFConfig", back_populates="purchases")


class BacktestRecord(Base):
    """Saved backtest result."""
    __tablename__ = "backtest_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    ticker = Column(String(10), index=True)
    backtest_start = Column(DateTime)
    backtest_end = Column(DateTime)
    total_budget = Column(Float)
    num_levels = Column(Integer)
    spacing_pct = Column(Float)
    weighting_method = Column(String(20))
    profit_target_pct = Column(Float)
    total_return_pct = Column(Float)
    annualized_return_pct = Column(Float)
    max_drawdown_pct = Column(Float)
    num_buys = Column(Integer)
    num_sells = Column(Integer)
    win_rate = Column(Float)
    result_json = Column(JSON)


class AnalysisCache(Base):
    """Cached historical analysis results."""
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), index=True)
    analysis_date = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    analysis_type = Column(String(20))
    result_json = Column(JSON)

    __table_args__ = (
        UniqueConstraint("ticker", "analysis_type", name="uix_ticker_type"),
    )
