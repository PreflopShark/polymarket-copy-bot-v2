"""
Resolution Friction Farm Bot - MVP

RULES:
1. Only deadline-based markets (crypto up/down)
2. Only trade AFTER deadline passes
3. Only BUY winners (no shorts)
4. Price must be <= 0.97 (minimum 3% profit)
"""
import asyncio
import logging
import signal
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List
from dataclasses import dataclass, field

from resolution_bot import config
from resolution_bot.oracle import DeadlineOracle

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@dataclass
class Position:
    market_id: str
    market_title: str
    token_id: str
    outcome: str
    shares: float
    entry_price: float
    entry_time: datetime
    
    @property
    def cost(self) -> float:
        return self.shares * self.entry_price
    
    @property
    def expected_profit(self) -> float:
        return self.shares * (1.0 - self.entry_price)


@dataclass 
class BotStats:
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    markets_checked: int = 0
    past_deadline: int = 0
    price_ok: int = 0
    trades_executed: int = 0
    total_invested: float = 0.0
    positions: List[Position] = field(default_factory=list)
    traded_markets: set = field(default_factory=set)


class ResolutionBot:
    GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        self.oracle = DeadlineOracle()
        self.stats = BotStats()
        self.running = False
    
    async def fetch_markets(self) -> List[Dict[str, Any]]:
        markets = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.GAMMA_API}/markets",
                    params={"active": "true", "closed": "false", "limit": 100},
                    timeout=10.0
                )
                if resp.status_code == 200:
                    for m in resp.json():
                        if self.oracle.is_crypto_updown(m):
                            markets.append(m)
        except Exception as e:
            logger.error(f"Fetch error: {e}")
        return markets
    
    async def check_and_trade(self, market: Dict[str, Any]) -> bool:
        market_id = market.get("condition_id", market.get("conditionId", ""))
        
        if market_id in self.stats.traded_markets:
            return False
        
        result = self.oracle.check_market(market)
        if not result:
            return False
        
        self.stats.markets_checked += 1
        
        if not result.is_past_deadline:
            return False
        
        self.stats.past_deadline += 1
        
        if not result.winner or not result.winner_price:
            return False
        
        # RULE 4: Price <= 0.97
        if result.winner_price > config.MAX_PRICE:
            return False
        
        self.stats.price_ok += 1
        
        profit_margin = 1.0 - result.winner_price
        position_cost = config.MAX_POSITION_SIZE
        shares = position_cost / result.winner_price
        expected_profit = shares * profit_margin
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("BUY WINNER")
        logger.info("=" * 60)
        logger.info(f"Market: {result.market_title}")
        logger.info(f"Winner: {result.winner}")
        logger.info(f"Price: ${result.winner_price:.4f}")
        logger.info(f"Margin: {profit_margin * 100:.1f}%")
        logger.info(f"Buy: {shares:.2f} shares for ${position_cost:.2f}")
        logger.info(f"Expected: +${expected_profit:.2f}")
        logger.info("=" * 60)
        
        if config.DRY_RUN:
            logger.info("[PAPER] Simulated")
            self.stats.positions.append(Position(
                market_id=market_id,
                market_title=result.market_title,
                token_id=result.winner_token_id or "",
                outcome=result.winner,
                shares=shares,
                entry_price=result.winner_price,
                entry_time=datetime.now(timezone.utc),
            ))
            self.stats.traded_markets.add(market_id)
            self.stats.trades_executed += 1
            self.stats.total_invested += position_cost
            return True
        
        logger.warning("Live trading not implemented")
        return False
    
    def print_status(self):
        runtime = (datetime.now(timezone.utc) - self.stats.start_time).total_seconds() / 60
        logger.info("")
        logger.info("=" * 50)
        logger.info("STATUS")
        logger.info(f"Runtime: {runtime:.1f} min")
        logger.info(f"Checked: {self.stats.markets_checked}")
        logger.info(f"Past deadline: {self.stats.past_deadline}")
        logger.info(f"Price OK: {self.stats.price_ok}")
        logger.info(f"Trades: {self.stats.trades_executed}")
        logger.info(f"Invested: ${self.stats.total_invested:.2f}")
        if self.stats.positions:
            profit = sum(p.expected_profit for p in self.stats.positions)
            logger.info(f"Expected: +${profit:.2f}")
        logger.info("=" * 50)
    
    async def run(self):
        logger.info("=" * 60)
        logger.info("Resolution Friction Bot - MVP")
        logger.info("=" * 60)
        logger.info("RULES:")
        logger.info("  1. Only deadline markets")
        logger.info("  2. Only AFTER deadline")
        logger.info("  3. Only BUY winners")
        logger.info(f"  4. Price <= ${config.MAX_PRICE:.2f}")
        if config.DRY_RUN:
            logger.info("[PAPER MODE]")
        logger.info(f"Max position: ${config.MAX_POSITION_SIZE}")
        logger.info("Scanning...")
        
        self.running = True
        iteration = 0
        
        while self.running:
            try:
                markets = await self.fetch_markets()
                for m in markets:
                    await self.check_and_trade(m)
                
                iteration += 1
                if iteration % 6 == 0:
                    self.print_status()
                
                await asyncio.sleep(config.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                await asyncio.sleep(5)
        
        self.print_status()
        logger.info("Stopped")
    
    def stop(self):
        self.running = False


async def main():
    bot = ResolutionBot()
    signal.signal(signal.SIGINT, lambda s, f: bot.stop())
    signal.signal(signal.SIGTERM, lambda s, f: bot.stop())
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
