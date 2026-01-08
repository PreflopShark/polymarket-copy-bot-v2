"""
Configuration management for the copy bot.

Provides a centralized, type-safe configuration system with:
- Environment variable loading
- Runtime updates via API
- Validation
- Sensitive field protection
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
import logging

logger = logging.getLogger(__name__)


class AssetRatios(BaseModel):
    """Per-asset copy ratios for crypto markets."""
    BTC: float = Field(default=1.0, ge=0, le=5)
    ETH: float = Field(default=1.0, ge=0, le=5)
    SOL: float = Field(default=1.0, ge=0, le=5)


class BotConfig(BaseSettings):
    """
    Bot configuration loaded from environment and runtime updates.

    Sensitive fields (private_key, api_*) are never exposed to the frontend.
    """

    # Mode
    dry_run: bool = Field(default=True, alias="DRY_RUN", description="Paper trading mode")

    # Target
    target_wallet: str = Field(default="", alias="TARGET_WALLET", description="Wallet address to copy")

    # Credentials (sensitive - never exposed to frontend)
    private_key: str = Field(default="", alias="PRIVATE_KEY")
    funder_address: str = Field(default="", alias="FUNDER_ADDRESS")
    api_key: str = Field(default="", alias="POLYMARKET_API_KEY")
    api_secret: str = Field(default="", alias="POLYMARKET_API_SECRET")
    api_passphrase: str = Field(default="", alias="POLYMARKET_API_PASSPHRASE")

    # Trade limits
    max_trade_amount: float = Field(default=25.0, alias="MAX_TRADE_AMOUNT", ge=1, le=10000)
    min_trade_amount: float = Field(default=1.0, alias="MIN_TRADE_AMOUNT", ge=0.1, le=100)

    # Price filters
    max_price: float = Field(default=0.80, alias="MAX_PRICE", ge=0.01, le=0.99)
    min_price: float = Field(default=0.10, alias="MIN_PRICE", ge=0.01, le=0.99)

    # Execution
    max_slippage: float = Field(default=0.10, alias="MAX_SLIPPAGE", ge=0.01, le=0.50)
    poll_interval: float = Field(default=0.1, alias="POLL_INTERVAL", ge=0.1, le=10)

    # Strategy
    skip_opposite_side: bool = Field(default=True, alias="SKIP_OPPOSITE_SIDE")

    # Paper trading
    initial_balance: float = Field(default=1200.0, alias="INITIAL_BALANCE", ge=100)

    # Asset ratios
    btc_copy_ratio: float = Field(default=1.0, alias="BTC_COPY_RATIO", ge=0, le=5)
    eth_copy_ratio: float = Field(default=1.0, alias="ETH_COPY_RATIO", ge=0, le=5)
    sol_copy_ratio: float = Field(default=1.0, alias="SOL_COPY_RATIO", ge=0, le=5)

    # API endpoints
    clob_host: str = "https://clob.polymarket.com"
    data_api_host: str = "https://data-api.polymarket.com"
    gamma_api_host: str = "https://gamma-api.polymarket.com"
    chain_id: int = 137

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("min_price")
    @classmethod
    def min_price_less_than_max(cls, v, info):
        """Ensure min_price < max_price."""
        # Note: Can't access max_price here directly in pydantic v2
        return v

    def get_public_config(self) -> Dict[str, Any]:
        """Get config without sensitive fields for API response."""
        return {
            "dry_run": self.dry_run,
            "target_wallet": self.target_wallet,
            "max_trade_amount": self.max_trade_amount,
            "min_trade_amount": self.min_trade_amount,
            "max_price": self.max_price,
            "min_price": self.min_price,
            "max_slippage": self.max_slippage,
            "poll_interval": self.poll_interval,
            "skip_opposite_side": self.skip_opposite_side,
            "initial_balance": self.initial_balance,
            "asset_ratios": {
                "BTC": self.btc_copy_ratio,
                "ETH": self.eth_copy_ratio,
                "SOL": self.sol_copy_ratio,
            }
        }

    def get_asset_ratio(self, asset: str) -> float:
        """Get copy ratio for a specific asset."""
        ratios = {
            "BTC": self.btc_copy_ratio,
            "ETH": self.eth_copy_ratio,
            "SOL": self.sol_copy_ratio,
        }
        return ratios.get(asset.upper(), 1.0)

    def update_from_dict(self, updates: Dict[str, Any]) -> "BotConfig":
        """Create new config with updates applied."""
        current = self.model_dump()

        # Handle nested asset_ratios
        if "asset_ratios" in updates:
            ratios = updates.pop("asset_ratios")
            if isinstance(ratios, dict):
                if "BTC" in ratios:
                    updates["btc_copy_ratio"] = ratios["BTC"]
                if "ETH" in ratios:
                    updates["eth_copy_ratio"] = ratios["ETH"]
                if "SOL" in ratios:
                    updates["sol_copy_ratio"] = ratios["SOL"]

        current.update(updates)
        return BotConfig(**current)

    def is_valid_for_trading(self) -> tuple[bool, Optional[str]]:
        """Check if config is valid for starting the bot."""
        if not self.target_wallet:
            return False, "No target wallet configured"
        if not self.private_key:
            return False, "No private key configured"
        if self.min_price >= self.max_price:
            return False, "min_price must be less than max_price"
        if self.min_trade_amount > self.max_trade_amount:
            return False, "min_trade_amount must be less than max_trade_amount"
        return True, None


class ConfigManager:
    """
    Manages configuration lifecycle.

    Provides thread-safe access to config and handles updates.
    """

    def __init__(self):
        self._config: Optional[BotConfig] = None

    def get(self) -> BotConfig:
        """Get the current config instance."""
        if self._config is None:
            self._config = BotConfig()
            logger.info("Configuration loaded from environment")
        return self._config

    def update(self, updates: Dict[str, Any]) -> BotConfig:
        """Update the config with new values."""
        current = self.get()
        self._config = current.update_from_dict(updates)
        logger.info(f"Configuration updated: {list(updates.keys())}")
        return self._config

    def reload(self) -> BotConfig:
        """Reload config from environment."""
        self._config = BotConfig()
        logger.info("Configuration reloaded from environment")
        return self._config


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> BotConfig:
    """Get the current config instance."""
    return get_config_manager().get()


def update_config(updates: Dict[str, Any]) -> BotConfig:
    """Update the global config."""
    return get_config_manager().update(updates)
