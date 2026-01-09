"""REST API routes for the copy bot."""

import re
import logging
from typing import Optional

import aiohttp
from fastapi import APIRouter, HTTPException

from ..config import get_config, update_config
from ..bot_manager import get_bot_manager, BotState
from ..models import (
    ConfigUpdateRequest,
    WalletValidateRequest,
    WalletValidateResponse,
    ApiResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config")
async def get_current_config():
    """Get current bot configuration (public fields only)."""
    config = get_config()
    return config.get_public_config()


@router.put("/config")
async def update_bot_config(request: ConfigUpdateRequest):
    """Update bot configuration. Only allowed when bot is stopped."""
    manager = get_bot_manager()

    if manager.state != BotState.STOPPED:
        raise HTTPException(
            status_code=400,
            detail="Cannot update config while bot is running"
        )

    # Convert request to dict, excluding None values
    updates = request.model_dump(exclude_none=True)

    # Handle nested asset_ratios
    if "asset_ratios" in updates and updates["asset_ratios"]:
        ratios = updates.pop("asset_ratios")
        if isinstance(ratios, dict):
            if "BTC" in ratios:
                updates["btc_copy_ratio"] = ratios["BTC"]
            if "ETH" in ratios:
                updates["eth_copy_ratio"] = ratios["ETH"]
            if "SOL" in ratios:
                updates["sol_copy_ratio"] = ratios["SOL"]

    new_config = update_config(updates)
    return {
        "success": True,
        "config": new_config.get_public_config()
    }


@router.post("/config/validate-wallet")
async def validate_wallet(request: WalletValidateRequest) -> WalletValidateResponse:
    """Validate a target wallet address or profile URL."""
    wallet_or_url = request.wallet_or_url.strip()

    # Extract address from URL if provided
    address = wallet_or_url

    # Handle Polymarket profile URLs
    # Format: https://polymarket.com/profile/0x... or https://polymarket.com/profile/username
    if "polymarket.com" in wallet_or_url:
        match = re.search(r'/profile/([^/?]+)', wallet_or_url)
        if match:
            address = match.group(1)

    # Check if it looks like an Ethereum address
    if address.startswith("0x") and len(address) == 42:
        # Validate hex
        try:
            int(address, 16)
        except ValueError:
            return WalletValidateResponse(
                valid=False,
                error="Invalid Ethereum address format"
            )

        # Try to fetch user info
        try:
            async with aiohttp.ClientSession() as session:
                # Check if address has activity
                url = f"https://data-api.polymarket.com/activity?user={address}&limit=1"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Try to get username from activity
                        username = None
                        if data and len(data) > 0:
                            username = data[0].get("pseudonym") or data[0].get("name")

                        return WalletValidateResponse(
                            valid=True,
                            address=address,
                            username=username
                        )
                    else:
                        return WalletValidateResponse(
                            valid=True,
                            address=address,
                            username=None
                        )
        except Exception as e:
            logger.warning(f"Error validating wallet: {e}")
            return WalletValidateResponse(
                valid=True,
                address=address,
                username=None
            )
    else:
        # Might be a username - try to resolve
        try:
            async with aiohttp.ClientSession() as session:
                # Search for user
                url = f"https://gamma-api.polymarket.com/users?name={address}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            user = data[0]
                            return WalletValidateResponse(
                                valid=True,
                                address=user.get("proxyWallet") or user.get("address"),
                                username=user.get("name") or user.get("pseudonym")
                            )
        except Exception as e:
            logger.warning(f"Error resolving username: {e}")

        return WalletValidateResponse(
            valid=False,
            error="Could not resolve username to address"
        )


@router.get("/bot/status")
async def get_bot_status():
    """Get current bot status."""
    manager = get_bot_manager()
    return manager.get_status()


@router.post("/bot/start")
async def start_bot():
    """Start the copy bot."""
    manager = get_bot_manager()
    result = await manager.start()

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/bot/stop")
async def stop_bot():
    """Stop the copy bot."""
    manager = get_bot_manager()
    result = await manager.stop()

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post("/bot/kill")
async def kill_bot():
    """Force kill the bot immediately without cleanup."""
    manager = get_bot_manager()
    result = await manager.kill()

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.get("/portfolio")
async def get_portfolio():
    """Get current portfolio state."""
    manager = get_bot_manager()
    return manager.get_portfolio()


@router.get("/trades/recent")
async def get_recent_trades(limit: int = 50):
    """Get recent trade activity."""
    manager = get_bot_manager()
    trades = manager.get_recent_trades(limit)
    return {"trades": trades}


@router.get("/session/summary")
async def get_session_summary():
    """Get last session summary."""
    manager = get_bot_manager()
    summary = manager.get_session_summary()

    if summary is None:
        return {"summary": None, "message": "No session data available"}

    return {"summary": summary}


@router.get("/portfolio/check-resolved")
async def check_resolved_markets():
    """
    Check for resolved markets and automatically redeem positions.

    For paper trading, this checks the Polymarket API for resolved markets
    and automatically settles positions, updating the balance and realized PnL.
    """
    manager = get_bot_manager()
    portfolio = manager.get_portfolio()

    if not portfolio.get("positions"):
        return {
            "resolved_positions": [],
            "newly_resolved": [],
            "total_resolved_pnl": portfolio.get("realized_pnl", 0),
            "message": "No positions to check"
        }

    newly_resolved = []
    total_pnl = 0

    # Get the paper trader to redeem positions
    paper_trader = None
    if manager._bot and manager._bot.executor:
        from ..services.paper_trader import PaperTrader
        if isinstance(manager._bot.executor, PaperTrader):
            paper_trader = manager._bot.executor

    # Check each position against resolved markets
    async with aiohttp.ClientSession() as session:
        for position in portfolio.get("positions", []):
            token_id = position.get("token_id")
            if not token_id:
                continue

            try:
                # Check market status via gamma API
                url = f"https://gamma-api.polymarket.com/markets?token_id={token_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            market = data[0]

                            # Check if market is resolved
                            if market.get("closed") or market.get("resolved"):
                                # Determine resolution price based on outcome
                                # The token we hold is either YES or NO
                                # If outcome matches our token, we win (price = 1.0)
                                outcome = market.get("outcome")
                                outcome_prices = market.get("outcomePrices", [])

                                # Get resolution price for this specific token
                                tokens = market.get("clobTokenIds", [])
                                resolution_price = 0.0
                                if tokens and token_id in tokens:
                                    idx = tokens.index(token_id)
                                    if outcome_prices and len(outcome_prices) > idx:
                                        try:
                                            resolution_price = float(outcome_prices[idx])
                                        except (ValueError, TypeError):
                                            # If outcome is truthy and this is first token (YES), price is 1
                                            resolution_price = 1.0 if outcome and idx == 0 else 0.0

                                # Redeem the position if we have paper trader
                                if paper_trader:
                                    result = paper_trader.redeem_position(token_id, resolution_price)
                                    if result:
                                        result["resolved_at"] = market.get("end_date_iso") or market.get("end_date")
                                        newly_resolved.append(result)
                                        total_pnl += result.get("pnl", 0)
                                        logger.info(f"Auto-redeemed: {result['market']} | PnL: ${result['pnl']:.2f}")

            except Exception as e:
                logger.warning(f"Error checking market resolution for {token_id}: {e}")
                continue

    # Get updated stats
    updated_portfolio = manager.get_portfolio()

    return {
        "newly_resolved": newly_resolved,
        "total_newly_resolved_pnl": total_pnl,
        "total_realized_pnl": updated_portfolio.get("realized_pnl", 0),
        "resolved_positions": updated_portfolio.get("resolved_positions", []),
        "positions_checked": len(portfolio.get("positions", [])),
        "positions_remaining": updated_portfolio.get("positions_count", 0),
    }
