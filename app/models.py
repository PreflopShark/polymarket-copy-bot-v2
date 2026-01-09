"""Pydantic models for API requests and responses."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class AssetRatios(BaseModel):
    """Per-asset copy ratios."""
    BTC: float = 1.0
    ETH: float = 1.0
    SOL: float = 1.0


class ConfigUpdateRequest(BaseModel):
    """Request model for config updates."""
    dry_run: Optional[bool] = None
    target_wallet: Optional[str] = None
    max_trade_amount: Optional[float] = None
    min_trade_amount: Optional[float] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    max_slippage: Optional[float] = None
    poll_interval: Optional[float] = None
    skip_opposite_side: Optional[bool] = None
    outcome_filter: Optional[str] = None  # 'all', 'up', or 'down'
    initial_balance: Optional[float] = None
    simulate_real_market: Optional[bool] = None
    asset_ratios: Optional[AssetRatios] = None


class WalletValidateRequest(BaseModel):
    """Request model for wallet validation."""
    wallet_or_url: str


class WalletValidateResponse(BaseModel):
    """Response model for wallet validation."""
    valid: bool
    address: Optional[str] = None
    username: Optional[str] = None
    error: Optional[str] = None


class BotStatusResponse(BaseModel):
    """Response model for bot status."""
    state: str
    start_time: Optional[str] = None
    runtime_seconds: Optional[float] = None
    stats: Optional[Dict[str, int]] = None
    skip_reasons: Optional[Dict[str, int]] = None
    paper: Optional[Dict[str, Any]] = None


class PortfolioResponse(BaseModel):
    """Response model for portfolio."""
    usdc_balance: float
    portfolio_value: float
    pnl: float
    pnl_percentage: float
    positions: List[Dict[str, Any]]


class TradeRecord(BaseModel):
    """Model for a trade record."""
    timestamp: str
    type: str  # detected, copied, skipped
    market: str
    side: str
    price: float
    size: float
    outcome: Optional[str] = None
    slippage: Optional[float] = None
    reason: Optional[str] = None


class SessionSummary(BaseModel):
    """Model for session summary."""
    start_time: Optional[str]
    end_time: str
    runtime_seconds: float
    runtime_formatted: str
    mode: str
    target_wallet: str
    stats: Dict[str, int]
    skip_reasons: Dict[str, int]
    paper: Optional[Dict[str, Any]] = None


class ApiResponse(BaseModel):
    """Generic API response."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Optional[Any] = None
