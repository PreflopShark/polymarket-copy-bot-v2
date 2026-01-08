"""Polymarket API client service."""

import logging
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

from ..config import BotConfig

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Handles Polymarket API connections."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.client: Optional[ClobClient] = None

    def connect(self) -> bool:
        """Initialize and verify connection to Polymarket."""
        logger.info("Connecting to Polymarket...")

        try:
            # Create CLOB client
            if self.config.funder_address:
                logger.info("Using proxy wallet (signature_type=1)")
                self.client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=1,
                    funder=self.config.funder_address,
                )
            else:
                logger.info("Using EOA wallet (signature_type=0)")
                self.client = ClobClient(
                    host=self.config.clob_host,
                    chain_id=self.config.chain_id,
                    key=self.config.private_key,
                    signature_type=0,
                )

            # Set API credentials
            if self.config.api_key:
                api_creds = ApiCreds(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    api_passphrase=self.config.api_passphrase,
                )
                self.client.set_api_creds(api_creds)
                logger.info("API credentials set")

            # Verify connection
            result = self.client.get_ok()
            logger.info(f"Connection verified: {result}")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def get_balance(self) -> Optional[float]:
        """Get USDC balance."""
        if not self.client:
            return None
        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_info = self.client.get_balance_allowance(params)
            raw_balance = float(balance_info.get("balance", 0))
            return raw_balance / 1_000_000  # Convert to USDC
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return None

    def get_order_book(self, token_id: str):
        """Get order book for a token."""
        if not self.client:
            return None
        try:
            return self.client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Failed to get order book: {e}")
            return None

    def disconnect(self):
        """Clean up client connection."""
        self.client = None
