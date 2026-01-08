"""Configuration management for the copy bot."""

import os
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class AssetRatios(BaseModel):
    """Per-asset copy ratios."""
    BTC: float = 1.0
    ETH: float = 1.0
    SOL: float = 1.0


class BotConfig(BaseSettings):
    """Bot configuration loaded from environment and runtime updates."""

    # Mode
    dry_run: bool = Field(default=True, alias="DRY_RUN")

    # Target
    target_wallet: str = Field(default="", alias="TARGET_WALLET")

    # Credentials (sensitive - never exposed to frontend)
    private_key: str = Field(default="", alias="PRIVATE_KEY")
    funder_address: str = Field(default="", alias="FUNDER_ADDRESS")
    api_key: str = Field(default="", alias="POLYMARKET_API_KEY")
    api_secret: str = Field(default="", alias="POLYMARKET_API_SECRET")
    api_passphrase: str = Field(default="", alias="POLYMARKET_API_PASSPHRASE")

    # Trade limits
    max_trade_amount: float = Field(default=25.0, alias="MAX_TRADE_AMOUNT")
    min_trade_amount: float = Field(default=1.0, alias="MIN_TRADE_AMOUNT")

    # Price filters
    max_price: float = Field(default=0.80, alias="MAX_PRICE")
    min_price: float = Field(default=0.10, alias="MIN_PRICE")

    # Execution
    max_slippage: float = Field(default=0.10, alias="MAX_SLIPPAGE")
    poll_interval: float = Field(default=0.1, alias="POLL_INTERVAL")

    # Strategy
    skip_opposite_side: bool = Field(default=True, alias="SKIP_OPPOSITE_SIDE")

    # Paper trading
    initial_balance: float = Field(default=1200.0, alias="INITIAL_BALANCE")

    # Asset ratios (stored separately)
    btc_copy_ratio: float = Field(default=1.0, alias="BTC_COPY_RATIO")
    eth_copy_ratio: float = Field(default=1.0, alias="ETH_COPY_RATIO")
    sol_copy_ratio: float = Field(default=1.0, alias="SOL_COPY_RATIO")

    # API endpoints (hardcoded)
    clob_host: str = "https://clob.polymarket.com"
    data_api_host: str = "https://data-api.polymarket.com"
    chain_id: int = 137

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_public_config(self) -> dict:
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

    def update_from_dict(self, updates: dict) -> "BotConfig":
        """Create new config with updates applied."""
        current = self.model_dump()

        # Handle nested asset_ratios
        if "asset_ratios" in updates:
            ratios = updates.pop("asset_ratios")
            if "BTC" in ratios:
                updates["btc_copy_ratio"] = ratios["BTC"]
            if "ETH" in ratios:
                updates["eth_copy_ratio"] = ratios["ETH"]
            if "SOL" in ratios:
                updates["sol_copy_ratio"] = ratios["SOL"]

        current.update(updates)
        return BotConfig(**current)


class ConfigUpdate(BaseModel):
    """Schema for config update requests."""
    dry_run: Optional[bool] = None
    target_wallet: Optional[str] = None
    max_trade_amount: Optional[float] = None
    min_trade_amount: Optional[float] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    max_slippage: Optional[float] = None
    poll_interval: Optional[float] = None
    skip_opposite_side: Optional[bool] = None
    initial_balance: Optional[float] = None
    asset_ratios: Optional[AssetRatios] = None


# Global config instance
_config: Optional[BotConfig] = None


def get_config() -> BotConfig:
    """Get the current config instance."""
    global _config
    if _config is None:
        _config = BotConfig()
    return _config


def update_config(updates: dict) -> BotConfig:
    """Update the global config."""
    global _config
    current = get_config()
    _config = current.update_from_dict(updates)
    return _config
