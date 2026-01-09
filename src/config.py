"""Configuration management for Polymarket Copy Trading Bot."""

import os
import re
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Config:
    """Bot configuration loaded from environment variables."""

    # Authentication
    private_key: str
    funder_address: str  # Proxy wallet address where funds are held

    # Target trader to copy
    target_trader_address: str

    # Trade sizing
    copy_ratio: float  # e.g., 0.1 = copy 10% of their trade size
    min_trade_amount: float  # Minimum USDC per trade
    max_trade_amount: float  # Maximum USDC per trade
    min_target_trade: float  # Only copy if target's trade >= this (signal filter)

    # Polling settings
    poll_interval_seconds: float  # How often to check for new trades

    # Dry run mode (paper trading)
    dry_run: bool  # If True, don't execute real trades
    initial_paper_balance: float  # Starting balance for paper trading

    # Builder API credentials (optional - if provided, uses these instead of deriving)
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""

    # Auto-redeem settings
    enable_auto_redeem: bool = True  # If True, periodically check for redeemable positions

    def __repr__(self) -> str:
        """Safe repr that masks the private key."""
        return (
            f"Config(private_key='****MASKED****', "
            f"target_trader_address='{self.target_trader_address}', "
            f"copy_ratio={self.copy_ratio}, "
            f"min_trade_amount={self.min_trade_amount}, "
            f"max_trade_amount={self.max_trade_amount}, "
            f"dry_run={self.dry_run})"
        )

    def __str__(self) -> str:
        """Safe string representation."""
        return self.__repr__()

    # Cloudflare bypass settings
    enable_browser_bypass: bool = False  # If True, use undetected-chromedriver to fetch CF cookies
    browser_headless: bool = True  # Run the browser in headless mode

    # Execution settings
    stale_order_timeout: float = 2.0  # Seconds to wait before canceling unfilled GTC orders
    max_slippage_percent: float = 15.0  # Maximum allowed slippage percentage
    max_hedge_imbalance_percent: float = 30.0  # Maximum hedge imbalance percentage
    skip_opposite_side: bool = True  # If True, don't copy trades for opposite side of markets we hold

    # Price filter thresholds
    max_price: float = 0.85  # Skip trades with price above this (near-certain outcomes)
    min_price: float = 0.15  # Skip trades with price below this (near-certain NO outcomes)

    # Conviction-based copy ratios (fallback for non-crypto markets)
    high_conviction_threshold: float = 200.0  # Trades >= this use high conviction ratio
    high_conviction_ratio: float = 0.20  # 20% copy ratio for large trades
    low_conviction_ratio: float = 0.03  # 3% copy ratio for smaller trades

    # Per-asset copy ratios for 15-minute crypto markets
    btc_copy_ratio: float = 0.02  # 2% for Bitcoin markets
    eth_copy_ratio: float = 0.03  # 3% for Ethereum markets
    sol_copy_ratio: float = 0.04  # 4% for Solana markets

    def get_copy_ratio_for_asset(self, asset_code: str) -> float:
        """Get the copy ratio for a specific crypto asset."""
        ratios = {
            "BTC": self.btc_copy_ratio,
            "ETH": self.eth_copy_ratio,
            "SOL": self.sol_copy_ratio,
        }
        return ratios.get(asset_code, self.low_conviction_ratio)

    def has_builder_api_credentials(self) -> bool:
        """Check if Builder API credentials are configured."""
        return bool(self.api_key and self.api_secret and self.api_passphrase)

    # Display settings
    market_name_max_len: int = 40  # Truncate market names to this length for display

    # API endpoints
    clob_host: str = "https://clob.polymarket.com"
    data_api_host: str = "https://data-api.polymarket.com"
    chain_id: int = 137  # Polygon mainnet

    # WebSocket settings
    use_websocket: bool = False  # Use WebSocket for trade detection (experimental)

    # Contrarian/Fade mode - bet OPPOSITE of target when slippage is high
    contrarian_mode: bool = False  # If True, take opposite side of target's trades
    contrarian_min_slippage: float = 20.0  # Only fade when slippage >= this % (price already moved)


def load_config() -> Config:
    """Load configuration from environment variables."""
    load_dotenv()

    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable is required")

    target_address = os.getenv("TARGET_TRADER_ADDRESS")
    if not target_address:
        raise ValueError("TARGET_TRADER_ADDRESS environment variable is required")
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", target_address.strip()):
        raise ValueError(
            "TARGET_TRADER_ADDRESS must be a 42-char hex address like 0x... (40 hex chars)"
        )

    funder_address = os.getenv("FUNDER_ADDRESS")
    if not funder_address:
        raise ValueError("FUNDER_ADDRESS environment variable is required")
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", funder_address.strip()):
        raise ValueError(
            "FUNDER_ADDRESS must be a 42-char hex address like 0x... (40 hex chars)"
        )

    return Config(
        private_key=private_key,
        funder_address=funder_address,
        api_key=os.getenv("POLYMARKET_API_KEY", ""),
        api_secret=os.getenv("POLYMARKET_API_SECRET", ""),
        api_passphrase=os.getenv("POLYMARKET_API_PASSPHRASE", ""),
        target_trader_address=target_address,
        copy_ratio=float(os.getenv("COPY_RATIO", "0.1")),
        min_trade_amount=float(os.getenv("MIN_TRADE_AMOUNT", "1.0")),
        max_trade_amount=float(os.getenv("MAX_TRADE_AMOUNT", "100.0")),
        min_target_trade=float(os.getenv("MIN_TARGET_TRADE", "0.0")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "2.0")),
        dry_run=os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes"),
        initial_paper_balance=float(os.getenv("INITIAL_PAPER_BALANCE", "1000.0")),
        enable_auto_redeem=os.getenv("ENABLE_AUTO_REDEEM", "true").lower() in ("true", "1", "yes"),
        enable_browser_bypass=os.getenv("ENABLE_BROWSER_BYPASS", "false").lower() in ("true", "1", "yes"),
        browser_headless=os.getenv("BROWSER_HEADLESS", "true").lower() in ("true", "1", "yes"),
        stale_order_timeout=float(os.getenv("STALE_ORDER_TIMEOUT", "2.0")),
        max_slippage_percent=float(os.getenv("MAX_SLIPPAGE_PERCENT", "15.0")),
        max_hedge_imbalance_percent=float(os.getenv("MAX_HEDGE_IMBALANCE_PERCENT", "30.0")),
        skip_opposite_side=os.getenv("SKIP_OPPOSITE_SIDE", "true").lower() in ("true", "1", "yes"),
        max_price=float(os.getenv("MAX_PRICE", "0.85")),
        min_price=float(os.getenv("MIN_PRICE", "0.15")),
        high_conviction_threshold=float(os.getenv("HIGH_CONVICTION_THRESHOLD", "200.0")),
        high_conviction_ratio=float(os.getenv("HIGH_CONVICTION_RATIO", "0.20")),
        low_conviction_ratio=float(os.getenv("LOW_CONVICTION_RATIO", "0.03")),
        btc_copy_ratio=float(os.getenv("BTC_COPY_RATIO", "0.02")),
        eth_copy_ratio=float(os.getenv("ETH_COPY_RATIO", "0.03")),
        sol_copy_ratio=float(os.getenv("SOL_COPY_RATIO", "0.04")),
        market_name_max_len=int(os.getenv("MARKET_NAME_MAX_LEN", "40")),
        use_websocket=os.getenv("USE_WEBSOCKET", "false").lower() in ("true", "1", "yes"),
        contrarian_mode=os.getenv("CONTRARIAN_MODE", "false").lower() in ("true", "1", "yes"),
        contrarian_min_slippage=float(os.getenv("CONTRARIAN_MIN_SLIPPAGE", "20.0")),
    )
