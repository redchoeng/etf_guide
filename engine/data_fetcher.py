import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class ETFDataFetcher:
    """yfinance data fetcher optimized for ETFs with caching & retry."""

    def __init__(self, config: dict):
        self.cache_dir = Path(config.get("cache_dir", "data/cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_expiry_hours = config.get("cache_expiry_hours", 4)
        self._memory_cache: dict[str, pd.DataFrame] = {}
        self._info_cache: dict[str, dict] = {}

    def fetch_history(self, ticker: str, period: str = "max",
                      start: str = None, end: str = None) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data with retry & MultiIndex flattening."""
        cache_key = f"{ticker}_{period}_{start}_{end}"
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        cached = self._load_disk_cache(ticker, period)
        if cached is not None:
            self._memory_cache[cache_key] = cached
            return cached

        for attempt in range(3):
            try:
                if start and end:
                    df = yf.download(ticker, start=start, end=end, progress=False)
                else:
                    df = yf.download(ticker, period=period, progress=False)

                if df is None or df.empty:
                    logger.warning(f"No data returned for {ticker}")
                    return None

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                self._memory_cache[cache_key] = df
                self._save_disk_cache(ticker, period, df)
                return df

            except Exception as e:
                err_str = str(e)
                if "401" in err_str or "Crumb" in err_str or "Unauthorized" in err_str:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Rate limited for {ticker}, waiting {wait}s (attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue
                logger.error(f"Error fetching {ticker}: {e}")
                if attempt < 2:
                    time.sleep(3)
                    continue
                return None

        logger.error(f"Failed to fetch {ticker} after 3 attempts")
        return None

    def batch_fetch(self, tickers: list[str], period: str = "5y") -> dict[str, pd.DataFrame]:
        """Batch download multiple ETFs."""
        result = {}
        batch_size = 10

        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            for attempt in range(3):
                try:
                    df = yf.download(batch, period=period, progress=False, group_by="ticker")
                    if df is None or df.empty:
                        break

                    for ticker in batch:
                        try:
                            if len(batch) == 1:
                                ticker_df = df.copy()
                            else:
                                ticker_df = df[ticker].copy()

                            if isinstance(ticker_df.columns, pd.MultiIndex):
                                ticker_df.columns = ticker_df.columns.get_level_values(0)

                            ticker_df = ticker_df.dropna(how="all")
                            if not ticker_df.empty:
                                result[ticker] = ticker_df
                                self._memory_cache[f"{ticker}_{period}_None_None"] = ticker_df
                        except (KeyError, Exception) as e:
                            logger.warning(f"Could not extract {ticker} from batch: {e}")
                    break

                except Exception as e:
                    if attempt < 2:
                        time.sleep(5 * (attempt + 1))
                        continue
                    logger.error(f"Batch fetch failed: {e}")

        return result

    def get_etf_info(self, ticker: str) -> dict:
        """Fetch ETF metadata."""
        if ticker in self._info_cache:
            return self._info_cache[ticker]

        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            result = {
                "name": info.get("longName") or info.get("shortName", ticker),
                "expense_ratio": info.get("annualReportExpenseRatio"),
                "inception_date": info.get("fundInceptionDate"),
                "category": info.get("category", ""),
                "total_assets": info.get("totalAssets"),
                "currency": info.get("currency", "USD"),
            }
            self._info_cache[ticker] = result
            return result
        except Exception as e:
            logger.warning(f"Could not fetch info for {ticker}: {e}")
            return {"name": ticker}

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get latest closing price."""
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"Could not get current price for {ticker}: {e}")
        return None

    def _load_disk_cache(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        cache_file = self.cache_dir / f"{ticker}_{period}.parquet"
        meta_file = self.cache_dir / f"{ticker}_{period}_meta.json"

        if not cache_file.exists() or not meta_file.exists():
            return None

        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
            cached_time = datetime.fromisoformat(meta["timestamp"])
            if datetime.now(timezone.utc) - cached_time.replace(tzinfo=timezone.utc) > timedelta(hours=self.cache_expiry_hours):
                return None
            return pd.read_parquet(cache_file)
        except Exception:
            return None

    def _save_disk_cache(self, ticker: str, period: str, df: pd.DataFrame):
        try:
            cache_file = self.cache_dir / f"{ticker}_{period}.parquet"
            meta_file = self.cache_dir / f"{ticker}_{period}_meta.json"
            df.to_parquet(cache_file)
            with open(meta_file, "w") as f:
                json.dump({"timestamp": datetime.now(timezone.utc).isoformat()}, f)
        except Exception as e:
            logger.warning(f"Could not save cache for {ticker}: {e}")
