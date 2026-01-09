"""Session logger for tracking bot runs and performance."""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)

# Polymarket API endpoints
DATA_API_HOST = "https://data-api.polymarket.com"


class SessionLogger:
    """Logs bot session statistics on startup and shutdown."""

    def __init__(self, config: Any):
        self.config = config
        self.start_time = datetime.now()
        self.trades_executed = 0
        self.trades_skipped = 0
        self.trades_failed = 0
        self.total_volume = 0.0

    def get_runtime(self) -> str:
        """Get formatted runtime duration."""
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

    def get_portfolio_value(self) -> Optional[float]:
        """Fetch portfolio value from Polymarket API."""
        try:
            url = f"{DATA_API_HOST}/value"
            params = {"user": self.config.funder_address}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # API returns a list with one item
                if isinstance(data, list) and len(data) > 0:
                    return float(data[0].get("value", 0))
                elif isinstance(data, dict):
                    return float(data.get("value", 0))
        except Exception as e:
            logger.error(f"Failed to fetch portfolio value: {e}")
        return None

    def get_positions_value(self) -> Optional[float]:
        """Fetch total positions value from Polymarket API."""
        try:
            url = f"{DATA_API_HOST}/positions"
            params = {"user": self.config.funder_address}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                positions = response.json()
                if isinstance(positions, list):
                    total = sum(
                        float(p.get("currentValue", 0) or 0)
                        for p in positions
                    )
                    return total
        except Exception as e:
            logger.error(f"Failed to fetch positions value: {e}")
        return None

    def get_cash_balance(self, client: Any = None) -> Optional[float]:
        """Fetch USDC cash balance."""
        if client:
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                balance_info = client.get_balance_allowance(params)
                raw_balance = float(balance_info.get("balance", 0))
                return raw_balance / 1_000_000  # Convert to USDC
            except Exception as e:
                logger.error(f"Failed to fetch cash balance via client: {e}")
        return None

    def increment_executed(self, volume: float = 0):
        """Track a successful trade."""
        self.trades_executed += 1
        self.total_volume += volume

    def increment_skipped(self):
        """Track a skipped trade."""
        self.trades_skipped += 1

    def increment_failed(self):
        """Track a failed trade."""
        self.trades_failed += 1

    def get_settings_summary(self) -> Dict[str, Any]:
        """Get current bot settings as a dictionary."""
        return {
            "target_trader": self.config.target_trader_address,
            "copy_ratio": f"{self.config.copy_ratio * 100:.0f}%",
            "btc_ratio": f"{self.config.btc_copy_ratio * 100:.0f}%",
            "eth_ratio": f"{self.config.eth_copy_ratio * 100:.0f}%",
            "sol_ratio": f"{self.config.sol_copy_ratio * 100:.0f}%",
            "min_trade": f"${self.config.min_trade_amount:.2f}",
            "max_trade": f"${self.config.max_trade_amount:.2f}",
            "max_slippage": f"{self.config.max_slippage_percent:.0f}%",
            "poll_interval": f"{self.config.poll_interval_seconds}s",
            "dry_run": self.config.dry_run,
        }

    def log_session_end(self, client: Any = None):
        """Log session summary on bot shutdown."""
        runtime = self.get_runtime()
        portfolio_value = self.get_portfolio_value()
        positions_value = self.get_positions_value()
        cash_balance = self.get_cash_balance(client)
        settings = self.get_settings_summary()

        logger.info("")
        logger.info("=" * 60)
        logger.info("SESSION END SUMMARY")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"Runtime: {runtime}")
        logger.info(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Ended:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")
        logger.info("--- BALANCES ---")
        if cash_balance is not None:
            logger.info(f"Cash Balance:     ${cash_balance:.2f}")
        else:
            logger.info("Cash Balance:     (unavailable)")
        if positions_value is not None:
            logger.info(f"Positions Value:  ${positions_value:.2f}")
        else:
            logger.info("Positions Value:  (unavailable)")
        if portfolio_value is not None:
            logger.info(f"Portfolio Total:  ${portfolio_value:.2f}")
        else:
            logger.info("Portfolio Total:  (unavailable)")
        logger.info("")
        logger.info("--- SESSION STATS ---")
        logger.info(f"Trades Executed:  {self.trades_executed}")
        logger.info(f"Trades Skipped:   {self.trades_skipped}")
        logger.info(f"Trades Failed:    {self.trades_failed}")
        logger.info(f"Total Volume:     ${self.total_volume:.2f}")
        logger.info("")
        logger.info("--- SETTINGS ---")
        logger.info(f"Target:           {settings['target_trader'][:20]}...")
        logger.info(f"Copy Ratio:       {settings['copy_ratio']} (BTC:{settings['btc_ratio']}, ETH:{settings['eth_ratio']}, SOL:{settings['sol_ratio']})")
        logger.info(f"Trade Limits:     {settings['min_trade']} - {settings['max_trade']}")
        logger.info(f"Max Slippage:     {settings['max_slippage']}")
        logger.info(f"Poll Interval:    {settings['poll_interval']}")
        logger.info(f"Mode:             {'DRY RUN' if settings['dry_run'] else 'LIVE'}")
        logger.info("")
        logger.info("=" * 60)

        # Also save to JSON file
        self._save_session_log(runtime, portfolio_value, positions_value, cash_balance, settings)

    def _save_session_log(
        self,
        runtime: str,
        portfolio_value: Optional[float],
        positions_value: Optional[float],
        cash_balance: Optional[float],
        settings: Dict[str, Any]
    ):
        """Save session log to JSON file."""
        log_data = {
            "session": {
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "runtime": runtime,
            },
            "balances": {
                "cash": cash_balance,
                "positions": positions_value,
                "portfolio_total": portfolio_value,
            },
            "stats": {
                "trades_executed": self.trades_executed,
                "trades_skipped": self.trades_skipped,
                "trades_failed": self.trades_failed,
                "total_volume": self.total_volume,
            },
            "settings": settings,
        }

        filename = f"session_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(filename, "w") as f:
                json.dump(log_data, f, indent=2)
            logger.info(f"Session log saved to: {filename}")
        except Exception as e:
            logger.error(f"Failed to save session log: {e}")


# Global session logger instance
_session_logger: Optional[SessionLogger] = None


def init_session_logger(config: Any) -> SessionLogger:
    """Initialize the global session logger."""
    global _session_logger
    _session_logger = SessionLogger(config)
    return _session_logger


def get_session_logger() -> Optional[SessionLogger]:
    """Get the global session logger instance."""
    return _session_logger
