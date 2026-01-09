"""
Market classifier for 15-minute crypto markets.
Detects BTC, ETH, SOL from market title strings.
"""

from enum import Enum


class CryptoAsset(Enum):
    """Supported crypto assets for per-asset copy ratios."""
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    UNKNOWN = "UNKNOWN"


def classify_market(market_name: str) -> CryptoAsset:
    """
    Classify a market by its crypto asset.

    Args:
        market_name: The market title (e.g., "Bitcoin Up or Down - January 7, 9:15PM-9:30PM ET")

    Returns:
        CryptoAsset enum value
    """
    if not market_name:
        return CryptoAsset.UNKNOWN

    name_lower = market_name.lower()

    if "bitcoin" in name_lower or "btc" in name_lower:
        return CryptoAsset.BTC
    if "ethereum" in name_lower or "eth" in name_lower:
        return CryptoAsset.ETH
    if "solana" in name_lower or "sol" in name_lower:
        return CryptoAsset.SOL

    return CryptoAsset.UNKNOWN
