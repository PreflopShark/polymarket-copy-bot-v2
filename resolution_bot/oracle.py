"""
Deadline-Based Resolution Oracle - MVP

RULES:
1. Find markets with deadlines (crypto up/down with specific times)
2. Check if deadline has PASSED
3. Determine WINNER based on market prices (higher price = winner)
4. Return winner info for buying
"""
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


@dataclass
class DeadlineResult:
    """Result from checking a deadline-based market"""
    market_id: str
    market_title: str
    is_past_deadline: bool
    winner: Optional[str]
    winner_token_id: Optional[str]
    winner_price: Optional[float]
    deadline: Optional[datetime]
    reasoning: str


class DeadlineOracle:
    """Oracle for deadline-based crypto markets."""
    
    CRYPTO_SYMBOLS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]
    
    def parse_deadline(self, title: str) -> Optional[datetime]:
        """Parse deadline time from market title."""
        # Time range pattern: "2:15AM-2:30AM"
        range_pattern = r"(\d{1,2}):?(\d{2})?(?:AM|PM)?-(\d{1,2}):?(\d{2})?(AM|PM)"
        range_match = re.search(range_pattern, title, re.IGNORECASE)
        
        if range_match:
            end_hour = int(range_match.group(3))
            end_min = int(range_match.group(4)) if range_match.group(4) else 0
            ampm = range_match.group(5).upper()
        else:
            time_pattern = r"(\d{1,2}):?(\d{2})?(AM|PM)"
            time_match = re.search(time_pattern, title, re.IGNORECASE)
            if not time_match:
                return None
            end_hour = int(time_match.group(1))
            end_min = int(time_match.group(2)) if time_match.group(2) else 0
            ampm = time_match.group(3).upper()
        
        if ampm == "PM" and end_hour != 12:
            end_hour += 12
        elif ampm == "AM" and end_hour == 12:
            end_hour = 0
        
        date_pattern = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})"
        date_match = re.search(date_pattern, title, re.IGNORECASE)
        if not date_match:
            return None
        
        month_map = {"january": 1, "february": 2, "march": 3, "april": 4,
                     "may": 5, "june": 6, "july": 7, "august": 8,
                     "september": 9, "october": 10, "november": 11, "december": 12}
        month = month_map.get(date_match.group(1).lower())
        day = int(date_match.group(2))
        
        if not month:
            return None
        
        try:
            return datetime(datetime.now().year, month, day, end_hour, end_min, tzinfo=ET)
        except ValueError:
            return None
    
    def is_crypto_updown(self, market: Dict[str, Any]) -> bool:
        """Check if this is a crypto up/down market"""
        title = market.get("question", market.get("title", "")).lower()
        return "up or down" in title and any(s in title for s in self.CRYPTO_SYMBOLS)
    
    def check_market(self, market: Dict[str, Any]) -> Optional[DeadlineResult]:
        """Check if deadline passed and determine winner."""
        title = market.get("question", market.get("title", ""))
        market_id = market.get("condition_id", market.get("conditionId", ""))
        
        if not self.is_crypto_updown(market):
            return None
        
        deadline = self.parse_deadline(title)
        if not deadline:
            return None
        
        now = datetime.now(ET)
        if now < deadline:
            return DeadlineResult(
                market_id=market_id, market_title=title,
                is_past_deadline=False, winner=None,
                winner_token_id=None, winner_price=None,
                deadline=deadline,
                reasoning=f"Deadline not passed. Now: {now.strftime('%H:%M')}, Deadline: {deadline.strftime('%H:%M')}"
            )
        
        # Get outcomes and prices
        outcomes = market.get("outcomes", ["Up", "Down"])
        prices = []
        if "outcomePrices" in market:
            price_data = market["outcomePrices"]
            if isinstance(price_data, str):
                price_data = price_data.strip("[]").split(",")
            prices = [float(p) for p in price_data]
        
        token_ids = []
        if "clobTokenIds" in market:
            tid_data = market["clobTokenIds"]
            if isinstance(tid_data, str):
                tid_data = tid_data.strip("[]").replace('"', '').split(",")
            token_ids = [t.strip() for t in tid_data]
        
        if not prices:
            return DeadlineResult(
                market_id=market_id, market_title=title,
                is_past_deadline=True, winner=None,
                winner_token_id=None, winner_price=None,
                deadline=deadline, reasoning="No price data"
            )
        
        winner_idx = prices.index(max(prices))
        winner = outcomes[winner_idx] if winner_idx < len(outcomes) else "Unknown"
        winner_price = prices[winner_idx]
        winner_token_id = token_ids[winner_idx] if winner_idx < len(token_ids) else None
        
        return DeadlineResult(
            market_id=market_id, market_title=title,
            is_past_deadline=True, winner=winner,
            winner_token_id=winner_token_id, winner_price=winner_price,
            deadline=deadline,
            reasoning=f"{winner} winning at ${winner_price:.4f}"
        )
