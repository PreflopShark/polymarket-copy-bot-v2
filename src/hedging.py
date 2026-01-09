"""
Hedging strategy to match target trader's balanced positions.

The target trader buys BOTH sides of binary markets (Up/Down, Yes/No).
This module tracks positions per market and ensures we maintain similar ratios.
"""

import logging
import time
import requests
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MarketPosition:
    """Track positions for both sides of a market."""
    condition_id: str
    market_name: str
    outcome_0_shares: float = 0.0  # Usually "Up" or "Yes"
    outcome_1_shares: float = 0.0  # Usually "Down" or "No"
    outcome_0_cost: float = 0.0
    outcome_1_cost: float = 0.0

    @property
    def total_shares(self) -> float:
        return self.outcome_0_shares + self.outcome_1_shares

    @property
    def total_cost(self) -> float:
        return self.outcome_0_cost + self.outcome_1_cost

    @property
    def balance_ratio(self) -> float:
        """Returns ratio of outcome_0 to total. 0.5 = perfectly balanced."""
        if self.total_shares == 0:
            return 0.5
        return self.outcome_0_shares / self.total_shares


@dataclass
class TargetTraderPosition:
    """Track what the target trader holds in a market."""
    condition_id: str
    outcome_0_shares: float = 0.0
    outcome_1_shares: float = 0.0
    fetched_at: float = 0.0  # When we last fetched from API

    @property
    def balance_ratio(self) -> float:
        total = self.outcome_0_shares + self.outcome_1_shares
        if total == 0:
            return 0.5
        return self.outcome_0_shares / total


class HedgingController:
    """
    Manages hedging strategy to mirror target trader's position ratios.

    Strategy:
    1. Track target trader's positions per market (both sides)
    2. Track our positions per market
    3. When copying a trade, check if it would unbalance us vs target
    4. Optionally skip trades that would make us more unbalanced
    """

    def __init__(self,
                 max_imbalance: float = 0.3,
                 copy_ratio: float = 0.15,
                 target_address: str = ""):
        """
        Args:
            max_imbalance: Max allowed deviation from target's ratio (0.3 = 30%)
            copy_ratio: Our copy ratio (to scale position tracking)
            target_address: Target trader's wallet address for API lookups
        """
        self.max_imbalance = max_imbalance
        self.copy_ratio = copy_ratio
        self.target_address = target_address

        # Track positions by condition_id
        self.our_positions: Dict[str, MarketPosition] = {}
        self.target_positions: Dict[str, TargetTraderPosition] = {}
        
        # Cache for target positions
        self._position_cache_ttl = 30.0  # Refresh target positions every 30 seconds
        self._last_full_refresh = 0.0

    def update_target_position(self,
                               condition_id: str,
                               outcome_index: int,
                               shares: float,
                               side: str):
        """Update what we know about target's position."""
        if condition_id not in self.target_positions:
            self.target_positions[condition_id] = TargetTraderPosition(
                condition_id=condition_id
            )

        pos = self.target_positions[condition_id]

        if side == "BUY":
            if outcome_index == 0:
                pos.outcome_0_shares += shares
            else:
                pos.outcome_1_shares += shares
        else:  # SELL
            if outcome_index == 0:
                pos.outcome_0_shares = max(0, pos.outcome_0_shares - shares)
            else:
                pos.outcome_1_shares = max(0, pos.outcome_1_shares - shares)

        logger.debug(f"Target position {condition_id[:16]}: "
                    f"O0={pos.outcome_0_shares:.1f}, O1={pos.outcome_1_shares:.1f}, "
                    f"ratio={pos.balance_ratio:.2f}")

    def update_our_position(self,
                           condition_id: str,
                           market_name: str,
                           outcome_index: int,
                           shares: float,
                           cost: float,
                           side: str):
        """Update our position after a trade."""
        if condition_id not in self.our_positions:
            self.our_positions[condition_id] = MarketPosition(
                condition_id=condition_id,
                market_name=market_name
            )

        pos = self.our_positions[condition_id]

        if side == "BUY":
            if outcome_index == 0:
                pos.outcome_0_shares += shares
                pos.outcome_0_cost += cost
            else:
                pos.outcome_1_shares += shares
                pos.outcome_1_cost += cost
        else:  # SELL
            if outcome_index == 0:
                pos.outcome_0_shares = max(0, pos.outcome_0_shares - shares)
            else:
                pos.outcome_1_shares = max(0, pos.outcome_1_shares - shares)

        logger.info(f"Our position {market_name[:30]}: "
                   f"O0={pos.outcome_0_shares:.1f}, O1={pos.outcome_1_shares:.1f}, "
                   f"ratio={pos.balance_ratio:.2f}")

    def should_copy_trade(self,
                         condition_id: str,
                         outcome_index: int,
                         shares: float,
                         side: str) -> Tuple[bool, str]:
        """
        Decide if we should copy this trade based on hedging strategy.

        Returns:
            (should_copy, reason)
        """
        # Always copy if we don't have target data
        if condition_id not in self.target_positions:
            return True, "No target position data - copying"

        target_pos = self.target_positions[condition_id]
        our_pos = self.our_positions.get(condition_id)

        # If we have no position, always copy
        if our_pos is None or our_pos.total_shares == 0:
            return True, "No existing position - copying"

        # Calculate what our ratio would be after this trade
        new_o0 = our_pos.outcome_0_shares
        new_o1 = our_pos.outcome_1_shares

        if side == "BUY":
            if outcome_index == 0:
                new_o0 += shares * self.copy_ratio
            else:
                new_o1 += shares * self.copy_ratio

        new_total = new_o0 + new_o1
        if new_total == 0:
            return True, "Would have no position - copying"

        new_ratio = new_o0 / new_total
        target_ratio = target_pos.balance_ratio

        # Check if this would make us more imbalanced than allowed
        imbalance = abs(new_ratio - target_ratio)

        if imbalance > self.max_imbalance:
            return False, f"Would create {imbalance*100:.1f}% imbalance vs target {target_ratio*100:.0f}%"

        return True, f"Within balance threshold ({imbalance*100:.1f}% vs max {self.max_imbalance*100:.0f}%)"

    def fetch_target_position(self, condition_id: str) -> Optional[TargetTraderPosition]:
        """
        Fetch target's ACTUAL position for a market from the API.
        
        This gives us real data instead of relying on incomplete trade tracking.
        """
        if not self.target_address:
            return None
        
        # Check cache freshness
        cached = self.target_positions.get(condition_id)
        if cached and (time.time() - cached.fetched_at) < self._position_cache_ttl:
            return cached
        
        try:
            url = f"https://data-api.polymarket.com/positions"
            params = {
                "user": self.target_address,
                "conditionId": condition_id,
                "sizeThreshold": 0,
            }
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch target position: {resp.status_code}")
                return cached  # Return stale cache if available
            
            positions = resp.json()
            if not positions:
                # Target has no position in this market
                return None
            
            # Sum up positions for both outcomes
            outcome_0_shares = 0.0
            outcome_1_shares = 0.0
            
            for pos in positions:
                outcome_idx = pos.get("outcomeIndex", 0)
                shares = float(pos.get("size", 0) or 0)
                if outcome_idx == 0 or "Up" in pos.get("outcome", "") or "Yes" in pos.get("outcome", ""):
                    outcome_0_shares += shares
                else:
                    outcome_1_shares += shares
            
            target_pos = TargetTraderPosition(
                condition_id=condition_id,
                outcome_0_shares=outcome_0_shares,
                outcome_1_shares=outcome_1_shares,
                fetched_at=time.time(),
            )
            self.target_positions[condition_id] = target_pos
            
            total = outcome_0_shares + outcome_1_shares
            if total > 0:
                ratio = outcome_0_shares / total * 100
                logger.info(f"Target position (API): {outcome_0_shares:.1f} Up / {outcome_1_shares:.1f} Down ({ratio:.0f}% Up)")
            
            return target_pos
            
        except Exception as e:
            logger.warning(f"Error fetching target position: {e}")
            return cached

    def get_target_sizing_weight(self, condition_id: str, outcome_index: int) -> float:
        """
        Get the weight multiplier based on target's ACTUAL sizing ratio for this outcome.
        
        FIXED: Now fetches real position data from API instead of relying on
        incremental trade tracking which was inaccurate.
        
        If target has 70% on Up and 30% on Down, returns:
        - 1.4 for Up (70/50)
        - 0.6 for Down (30/50)
        
        This helps us weight our bets to match target's conviction.
        
        Returns:
            Weight multiplier (1.0 = neutral, >1 = target favors this side)
        """
        # Fetch actual position from API (cached)
        target_pos = self.fetch_target_position(condition_id)
        
        if target_pos is None:
            return 1.0  # No data, use neutral weight
        
        total = target_pos.outcome_0_shares + target_pos.outcome_1_shares
        
        if total == 0:
            return 1.0
        
        # Calculate target's allocation to this outcome
        if outcome_index == 0:
            target_allocation = target_pos.outcome_0_shares / total
        else:
            target_allocation = target_pos.outcome_1_shares / total
        
        # Convert to weight: 0.5 allocation = 1.0 weight, 0.7 = 1.4 weight, 0.3 = 0.6 weight
        weight = target_allocation * 2.0
        
        logger.info(f"Target sizing weight for outcome {outcome_index}: {weight:.2f} "
                   f"(target has {target_allocation*100:.0f}% on this side, from API)")
        
        return weight

    def is_target_dominant_side(self, condition_id: str, outcome_index: int, min_dominance: float = 0.55) -> Tuple[bool, str]:
        """
        Check if this outcome is target's dominant side (where they have majority allocation).
        
        This prevents us from copying minority-side trades. If target has 70% DOWN and 30% UP,
        we should ONLY copy DOWN trades and skip UP trades.
        
        Args:
            condition_id: The market condition ID
            outcome_index: 0 for Up/Yes, 1 for Down/No
            min_dominance: Minimum allocation to consider "dominant" (default 55%)
        
        Returns:
            (is_dominant, reason_string)
        """
        target_pos = self.fetch_target_position(condition_id)
        
        if target_pos is None:
            return True, "No target position data - allowing trade"
        
        total = target_pos.outcome_0_shares + target_pos.outcome_1_shares
        
        if total < 10:  # Less than 10 shares total - not enough data
            return True, "Target position too small - allowing trade"
        
        # Calculate target's allocation to this outcome
        if outcome_index == 0:
            target_allocation = target_pos.outcome_0_shares / total
            side_name = "Up/Yes"
        else:
            target_allocation = target_pos.outcome_1_shares / total
            side_name = "Down/No"
        
        # Check if this is the dominant side
        if target_allocation >= min_dominance:
            return True, f"Trade is on target's dominant side ({side_name} = {target_allocation*100:.0f}%)"
        elif target_allocation <= (1 - min_dominance):
            # This is the minority side - SKIP
            dominant_side = "Down/No" if outcome_index == 0 else "Up/Yes"
            dominant_pct = (1 - target_allocation) * 100
            return False, f"SKIP: Target favors {dominant_side} ({dominant_pct:.0f}%), this is minority side ({target_allocation*100:.0f}%)"
        else:
            # Close to 50/50 - allow both sides
            return True, f"Target position is balanced ({target_allocation*100:.0f}%) - allowing trade"

    def get_position_summary(self) -> str:
        """Get a summary of all positions."""
        lines = ["=== POSITION SUMMARY ==="]

        for cid, pos in self.our_positions.items():
            target = self.target_positions.get(cid)
            target_ratio = target.balance_ratio if target else "?"

            lines.append(
                f"{pos.market_name[:40]}: "
                f"Ours O0={pos.outcome_0_shares:.1f}/O1={pos.outcome_1_shares:.1f} "
                f"(ratio={pos.balance_ratio:.2f}) | "
                f"Target ratio={target_ratio}"
            )

        return "\n".join(lines)


def create_hedging_controller(max_imbalance_pct: float = 30.0,
                              copy_ratio: float = 0.15,
                              target_address: str = "") -> HedgingController:
    """Factory function to create hedging controller."""
    return HedgingController(
        max_imbalance=max_imbalance_pct / 100,
        copy_ratio=copy_ratio,
        target_address=target_address
    )
