import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.models import (
    Base, ETFConfig, GridLevelRecord, PurchaseRecord,
    BacktestRecord, AnalysisCache,
)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        storage_cfg = config.get("storage", {})
        db_type = storage_cfg.get("db_type", "sqlite")

        if db_type == "sqlite":
            db_path = storage_cfg.get("sqlite_path", "data/etf_guide.db")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{db_path}"
        else:
            import os
            url = os.environ.get("DATABASE_URL", f"sqlite:///data/etf_guide.db")

        self.engine = create_engine(url, echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    @contextmanager
    def get_session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # --- ETF Config ---
    def save_etf_config(self, data: dict) -> int:
        with self.get_session() as session:
            obj = ETFConfig(**data)
            session.add(obj)
            session.flush()
            return obj.id

    def get_etf_config(self, ticker: str) -> Optional[dict]:
        with self.get_session() as session:
            obj = session.query(ETFConfig).filter_by(ticker=ticker).first()
            if not obj:
                return None
            return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    def get_all_etf_configs(self) -> list[dict]:
        with self.get_session() as session:
            rows = session.query(ETFConfig).filter_by(active=True).all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    def update_etf_config(self, ticker: str, updates: dict):
        with self.get_session() as session:
            obj = session.query(ETFConfig).filter_by(ticker=ticker).first()
            if obj:
                for k, v in updates.items():
                    setattr(obj, k, v)

    def delete_etf_config(self, ticker: str):
        with self.get_session() as session:
            obj = session.query(ETFConfig).filter_by(ticker=ticker).first()
            if obj:
                session.delete(obj)

    # --- Grid Levels ---
    def save_grid_levels(self, etf_config_id: int, levels: list[dict]):
        with self.get_session() as session:
            session.query(GridLevelRecord).filter_by(
                etf_config_id=etf_config_id
            ).delete()
            for lv in levels:
                lv["etf_config_id"] = etf_config_id
                session.add(GridLevelRecord(**lv))

    def get_grid_levels(self, ticker: str) -> list[dict]:
        with self.get_session() as session:
            cfg = session.query(ETFConfig).filter_by(ticker=ticker).first()
            if not cfg:
                return []
            rows = (
                session.query(GridLevelRecord)
                .filter_by(etf_config_id=cfg.id)
                .order_by(GridLevelRecord.level_number)
                .all()
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    def mark_level_filled(self, level_id: int, price: float, quantity: int,
                          date: datetime):
        with self.get_session() as session:
            obj = session.query(GridLevelRecord).get(level_id)
            if obj:
                obj.is_filled = True
                obj.filled_price = price
                obj.filled_quantity = quantity
                obj.filled_date = date

    # --- Purchases ---
    def save_purchase(self, data: dict):
        with self.get_session() as session:
            session.add(PurchaseRecord(**data))

    def get_purchases(self, ticker: str = None) -> list[dict]:
        with self.get_session() as session:
            q = session.query(PurchaseRecord)
            if ticker:
                q = q.filter_by(ticker=ticker)
            rows = q.order_by(PurchaseRecord.purchase_date.desc()).all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    def get_portfolio_summary(self) -> list[dict]:
        with self.get_session() as session:
            configs = session.query(ETFConfig).filter_by(active=True).all()
            result = []
            for cfg in configs:
                purchases = (
                    session.query(PurchaseRecord)
                    .filter_by(etf_config_id=cfg.id)
                    .all()
                )
                total_shares = sum(p.quantity for p in purchases)
                total_cost = sum(p.total_cost for p in purchases)
                avg_cost = total_cost / total_shares if total_shares > 0 else 0
                result.append({
                    "ticker": cfg.ticker,
                    "name": cfg.name,
                    "total_shares": total_shares,
                    "total_cost": total_cost,
                    "avg_cost": avg_cost,
                    "leverage": cfg.leverage_factor,
                })
            return result

    # --- Backtests ---
    def save_backtest(self, data: dict):
        with self.get_session() as session:
            session.add(BacktestRecord(**data))

    def get_backtests(self, ticker: str = None) -> list[dict]:
        with self.get_session() as session:
            q = session.query(BacktestRecord)
            if ticker:
                q = q.filter_by(ticker=ticker)
            rows = q.order_by(BacktestRecord.run_date.desc()).all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    # --- Analysis Cache ---
    def save_analysis(self, ticker: str, analysis_type: str, result: dict):
        with self.get_session() as session:
            existing = (
                session.query(AnalysisCache)
                .filter_by(ticker=ticker, analysis_type=analysis_type)
                .first()
            )
            if existing:
                existing.result_json = result
                existing.analysis_date = datetime.now(timezone.utc)
            else:
                session.add(AnalysisCache(
                    ticker=ticker,
                    analysis_type=analysis_type,
                    result_json=result,
                ))

    def get_cached_analysis(self, ticker: str, analysis_type: str,
                            max_age_hours: int = 24) -> Optional[dict]:
        with self.get_session() as session:
            obj = (
                session.query(AnalysisCache)
                .filter_by(ticker=ticker, analysis_type=analysis_type)
                .first()
            )
            if not obj:
                return None
            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            if obj.analysis_date.replace(tzinfo=timezone.utc) < cutoff:
                return None
            return obj.result_json
