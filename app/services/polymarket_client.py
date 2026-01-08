"""
Polymarket API client service.

Implements the TradingClient interface for Polymarket operations.
"""

import logging
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

from ..config import BotConfig
from ..core.interfaces import TradingClient, OrderBookInfo, ExecutionResult
from ..core.exceptions import ConnectionError

logger = logging.getLogger(__name__)


class PolymarketClient(TradingClient):
    """
    Polymarket trading client implementation.

    Handles connection, balance queries, and order book access.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self._client: Optional[ClobClient] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._client is not None

    def connect(self) -> bool:
        """Initialize and verify connection to Polymarket."""
        logger.info("Connecting to Polymarket...")

        try:
            # Create CLOB client based on wallet type
            if self.config.funder_address:
                logger.info("Using proxy wallet (signature_type=1)")
                self._client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=1,
                    funder=self.config.funder_address,
                )
            else:
                logger.info("Using EOA wallet (signature_type=0)")
                self._client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=0,
                )

            # Set API credentials if available
            if self.config.api_key:
                api_creds = ApiCreds(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    api_passphrase=self.config.api_passphrase,
                )
                self._client.set_api_creds(api_creds)
                logger.info("API credentials configured")

            # Verify connection
            result = self._client.get_ok()
            logger.info(f"Connection verified: {result}")
            self._connected = True
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to Polymarket: {e}")

    def disconnect(self) -> None:
        """Clean up client connection."""
        self._client = None
        self._connected = False
        logger.info("Disconnected from Polymarket")

    def get_balance(self) -> Optional[float]:
        """Get USDC balance in dollars."""
        if not self.is_connected:
            return None

        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_info = self._client.get_balance_allowance(params)
            raw_balance = float(balance_info.get("balance", 0))
            return raw_balance / 1_000_000  # Convert from micro-USDC
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None

    def get_order_book(self, token_id: str) -> Optional[OrderBookInfo]:
        """Get order book for a token."""
        if not self.is_connected:
            return None

        try:
            book = self._client.get_order_book(token_id)

            best_bid = None
            best_ask = None
            bid_depth = 0.0
            ask_depth = 0.0

            if book.bids:
                sorted_bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True)
                best_bid = float(sorted_bids[0].price)
                bid_depth = sum(float(b.size) for b in book.bids)

            if book.asks:
                sorted_asks = sorted(book.asks, key=lambda x: float(x.price))
                best_ask = float(sorted_asks[0].price)
                ask_depth = sum(float(a.size) for a in book.asks)

            return OrderBookInfo(
                best_bid=best_bid,
                best_ask=best_ask,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
            )

        except Exception as e:
            logger.error(f"Failed to get order book: {e}")
            return None

    def get_raw_order_book(self, token_id: str):
        """Get raw order book object (for advanced operations)."""
        if not self.is_connected:
            return None
        try:
            return self._client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Failed to get order book: {e}")
            return None

    async def execute_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> ExecutionResult:
        """
        Execute a trade order.

        For now, this is a placeholder - actual execution is handled
        by the paper trader in dry run mode.
        """
        # In dry run mode, this shouldn't be called directly
        # Live trading implementation would go here
        return ExecutionResult(
            success=False,
            status="not_implemented",
            message="Live trading not yet implemented",
        )
