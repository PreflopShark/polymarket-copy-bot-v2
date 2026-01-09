"""
Position Intelligence for Copy Trading Bot

Tracks target trader's positions and provides intelligent copy decisions based on:
- Trade classification (initial entry, scale-in, major scale, hedge, exit)
- Conviction scoring (size percentile, scaling factor, time urgency)
- Smart hedge copying (only copy when hedge ratio >= threshold)
- Time-aware sizing (increase size near market close)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import re

logger = logging.getLogger(__name__)


class TradeClassification(str, Enum):
    """Classification of trade types based on position context."""
    INITIAL_ENTRY = "initial_entry"      # First trade in a market
    SCALE_IN = "scale_in"                # Adding to existing position
    MAJOR_SCALE = "major_scale"          # 3x+ addition to position
    HEDGE = "hedge"                      # Opposite side trade
    EXIT = "exit"                        # Selling existing position
    UNKNOWN = "unknown"


@dataclass
class TargetPosition:
    """Tracks target's position in a single market."""
    market_slug: str
    primary_side: str                    # "UP" or "DOWN"
    total_size: float
    entry_count: int
    first_entry_size: float
    first_entry_time: datetime
    last_entry_time: datetime
    hedge_size: float = 0.0
    trades: List[Dict] = field(default_factory=list)

    @property
    def hedge_ratio(self) -> float:
        """Calculate hedge ratio (hedge_size / total_primary_size)."""
        if self.total_size <= 0:
            return 0.0
        return self.hedge_size / self.total_size

    @property
    def scaling_factor(self) -> float:
        """How much the position has scaled from first entry."""
        if self.first_entry_size <= 0:
            return 1.0
        return self.total_size / self.first_entry_size

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "market_slug": self.market_slug,
            "primary_side": self.primary_side,
            "total_size": self.total_size,
            "entry_count": self.entry_count,
            "first_entry_size": self.first_entry_size,
            "scaling_factor": self.scaling_factor,
            "hedge_size": self.hedge_size,
            "hedge_ratio": self.hedge_ratio,
            "first_entry_time": self.first_entry_time.isoformat(),
            "last_entry_time": self.last_entry_time.isoformat(),
        }


@dataclass
class ConvictionScore:
    """Conviction score based on multiple signals."""
    size_percentile: float      # 0-1: where this trade size ranks historically
    scaling_factor: float       # How much trader has scaled into this position
    time_urgency: float         # 0-1: proximity to market close
    is_major_scale: bool        # 3x+ addition
    classification: TradeClassification

    # Weights for scoring
    SIZE_WEIGHT = 0.3
    SCALING_WEIGHT = 0.3
    TIME_WEIGHT = 0.25
    MAJOR_SCALE_BONUS = 15

    def total_score(self) -> int:
        """Calculate total conviction score (0-100)."""
        base_score = (
            self.size_percentile * self.SIZE_WEIGHT * 100 +
            min(self.scaling_factor / 5, 1.0) * self.SCALING_WEIGHT * 100 +
            self.time_urgency * self.TIME_WEIGHT * 100
        )

        # Bonus for major scale-ins
        if self.is_major_scale:
            base_score += self.MAJOR_SCALE_BONUS

        return int(min(100, max(0, base_score)))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_score": self.total_score(),
            "size_percentile": self.size_percentile,
            "scaling_factor": self.scaling_factor,
            "time_urgency": self.time_urgency,
            "is_major_scale": self.is_major_scale,
            "classification": self.classification.value,
        }


@dataclass
class CopyDecision:
    """Decision on whether and how to copy a trade."""
    skip: bool
    reason: str = ""
    size: float = 0.0
    conviction: Optional[ConvictionScore] = None
    classification: TradeClassification = TradeClassification.UNKNOWN
    position: Optional[TargetPosition] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "skip": self.skip,
            "reason": self.reason,
            "size": self.size,
            "conviction": self.conviction.to_dict() if self.conviction else None,
            "classification": self.classification.value,
        }


class TargetPositionTracker:
    """Tracks all of target's current positions."""

    def __init__(self, major_scale_threshold: float = 3.0):
        self._positions: Dict[str, TargetPosition] = {}
        self._major_scale_threshold = major_scale_threshold
        self._market_close_times: Dict[str, datetime] = {}

    def add_trade(self, trade_info, market_slug: str) -> Tuple[TradeClassification, Optional[TargetPosition]]:
        """
        Add a trade and classify it.
        Returns (classification, position).
        """
        outcome = (trade_info.outcome or "").upper()
        side = (trade_info.side or "").upper()
        size = trade_info.size
        timestamp = datetime.fromtimestamp(trade_info.timestamp)

        # Handle SELL trades
        if side == "SELL":
            if market_slug in self._positions:
                position = self._positions[market_slug]
                # If selling primary side, it's an exit
                if outcome == position.primary_side:
                    position.total_size = max(0, position.total_size - size)
                    return TradeClassification.EXIT, position
                else:
                    # Selling hedge side
                    position.hedge_size = max(0, position.hedge_size - size)
                    return TradeClassification.EXIT, position
            return TradeClassification.EXIT, None

        # Handle BUY trades
        if market_slug not in self._positions:
            # New position - initial entry
            position = TargetPosition(
                market_slug=market_slug,
                primary_side=outcome,
                total_size=size,
                entry_count=1,
                first_entry_size=size,
                first_entry_time=timestamp,
                last_entry_time=timestamp,
                trades=[{"outcome": outcome, "size": size, "timestamp": timestamp}],
            )
            self._positions[market_slug] = position
            return TradeClassification.INITIAL_ENTRY, position

        position = self._positions[market_slug]

        # Check if this is opposite side (hedge)
        if outcome != position.primary_side:
            position.hedge_size += size
            position.trades.append({"outcome": outcome, "size": size, "timestamp": timestamp})
            return TradeClassification.HEDGE, position

        # Same side - scale-in
        prev_size = position.total_size
        position.total_size += size
        position.entry_count += 1
        position.last_entry_time = timestamp
        position.trades.append({"outcome": outcome, "size": size, "timestamp": timestamp})

        # Check for major scale (3x+ in single trade)
        scale_ratio = size / position.first_entry_size if position.first_entry_size > 0 else 1.0

        if scale_ratio >= self._major_scale_threshold:
            return TradeClassification.MAJOR_SCALE, position

        return TradeClassification.SCALE_IN, position

    def get_position(self, market_slug: str) -> Optional[TargetPosition]:
        """Get position for a market."""
        return self._positions.get(market_slug)

    def get_all_positions(self) -> Dict[str, TargetPosition]:
        """Get all current positions."""
        return self._positions.copy()

    def cleanup_old_positions(self, max_age_minutes: int = 30) -> None:
        """Remove positions older than max_age."""
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        expired = [
            slug for slug, pos in self._positions.items()
            if pos.last_entry_time < cutoff
        ]
        for slug in expired:
            del self._positions[slug]

    def reset(self) -> None:
        """Reset all tracking."""
        self._positions.clear()


class HedgeCopyStrategy:
    """Determines if and how to copy hedge trades."""

    def __init__(self, target_hedge_ratio: float = 0.25):
        self._target_hedge_ratio = target_hedge_ratio

    def should_copy_hedge(
        self,
        trade_size: float,
        position: TargetPosition
    ) -> Tuple[bool, float, str]:
        """
        Determine if we should copy a hedge trade.
        Returns (should_copy, size_to_copy, reason).
        """
        # Calculate what the hedge ratio would be after this trade
        new_hedge_size = position.hedge_size
        new_hedge_ratio = new_hedge_size / position.total_size if position.total_size > 0 else 0

        # If hedge ratio is below target, skip (trader still building position)
        if new_hedge_ratio < self._target_hedge_ratio:
            return False, 0.0, f"Hedge ratio {new_hedge_ratio:.0%} < target {self._target_hedge_ratio:.0%}"

        # Copy proportionally to maintain similar hedge ratio
        # We want our hedge to be about target_hedge_ratio of our position
        copy_size = trade_size * (self._target_hedge_ratio / max(new_hedge_ratio, 0.01))
        copy_size = min(copy_size, trade_size)  # Don't copy more than original

        return True, copy_size, f"Hedge ratio {new_hedge_ratio:.0%} >= target, copying {copy_size:.2f}"


class CopySizer:
    """Determines copy size based on conviction and configuration."""

    def __init__(
        self,
        base_ratio: float = 1.0,
        max_trade_amount: float = 25.0,
        min_trade_amount: float = 1.0,
        time_urgency_multiplier: float = 2.0,
        conviction_sizing_enabled: bool = True,
    ):
        self._base_ratio = base_ratio
        self._max_trade_amount = max_trade_amount
        self._min_trade_amount = min_trade_amount
        self._time_urgency_multiplier = time_urgency_multiplier
        self._conviction_sizing_enabled = conviction_sizing_enabled

    def calculate_size(
        self,
        trade_size: float,
        conviction: ConvictionScore,
        classification: TradeClassification,
    ) -> float:
        """Calculate our copy size based on conviction."""
        if not self._conviction_sizing_enabled:
            # Simple sizing without conviction
            return min(max(trade_size * self._base_ratio, self._min_trade_amount), self._max_trade_amount)

        base = trade_size * self._base_ratio

        # Apply conviction multiplier (0.5x to 2x based on score)
        conviction_score = conviction.total_score()
        conviction_mult = 0.5 + (conviction_score / 100) * 1.5

        # Apply time urgency multiplier (1x to time_urgency_multiplier in final 5 min)
        time_mult = 1.0 + (conviction.time_urgency * (self._time_urgency_multiplier - 1.0))

        # Reduce size for initial entries (wait for confirmation)
        if classification == TradeClassification.INITIAL_ENTRY:
            conviction_mult *= 0.6  # 40% reduction for first entry

        # Increase size for major scale-ins
        if classification == TradeClassification.MAJOR_SCALE:
            conviction_mult *= 1.3  # 30% bonus for major scale

        final_size = base * conviction_mult * time_mult

        # Apply limits
        final_size = max(final_size, self._min_trade_amount)
        final_size = min(final_size, self._max_trade_amount)

        return final_size


class PositionIntelligence:
    """
    Coordinates position tracking and intelligent copy decisions.

    Combines:
    - Position tracking (scaling patterns)
    - Trade classification
    - Conviction scoring
    - Smart hedge copying
    - Time-aware sizing
    """

    def __init__(
        self,
        position_tracking_enabled: bool = True,
        conviction_sizing_enabled: bool = True,
        target_hedge_ratio: float = 0.25,
        time_urgency_multiplier: float = 2.0,
        major_scale_threshold: float = 3.0,
        max_trade_amount: float = 25.0,
        min_trade_amount: float = 1.0,
    ):
        self._enabled = position_tracking_enabled
        self._position_tracker = TargetPositionTracker(major_scale_threshold)
        self._hedge_strategy = HedgeCopyStrategy(target_hedge_ratio)
        self._copy_sizer = CopySizer(
            base_ratio=1.0,
            max_trade_amount=max_trade_amount,
            min_trade_amount=min_trade_amount,
            time_urgency_multiplier=time_urgency_multiplier,
            conviction_sizing_enabled=conviction_sizing_enabled,
        )

        # Trade history for percentile calculation
        self._trade_sizes: List[float] = []
        self._max_history = 500

    def process_trade(self, trade_info) -> CopyDecision:
        """
        Process a trade and return copy decision.

        This is the main entry point for the copy bot to use.
        """
        if not self._enabled:
            # Passthrough mode - just return basic decision
            return CopyDecision(
                skip=False,
                size=trade_info.size,
                classification=TradeClassification.UNKNOWN,
            )

        # Normalize market name to slug
        market_slug = self._normalize_market(trade_info.market_name)

        # Add trade to history for percentile calculation
        self._trade_sizes.append(trade_info.size)
        if len(self._trade_sizes) > self._max_history:
            self._trade_sizes.pop(0)

        # Classify the trade
        classification, position = self._position_tracker.add_trade(trade_info, market_slug)

        # Calculate conviction
        conviction = self._calculate_conviction(trade_info, position, classification)

        # Handle based on classification
        if classification == TradeClassification.EXIT:
            return CopyDecision(
                skip=True,
                reason="Exit trade (SELL)",
                classification=classification,
                position=position,
            )

        if classification == TradeClassification.HEDGE:
            should_copy, size, reason = self._hedge_strategy.should_copy_hedge(
                trade_info.size,
                position
            )
            if not should_copy:
                return CopyDecision(
                    skip=True,
                    reason=reason,
                    classification=classification,
                    conviction=conviction,
                    position=position,
                )
            return CopyDecision(
                skip=False,
                size=size,
                classification=classification,
                conviction=conviction,
                position=position,
                reason=reason,
            )

        # Regular trade (INITIAL_ENTRY, SCALE_IN, MAJOR_SCALE)
        size = self._copy_sizer.calculate_size(trade_info.size, conviction, classification)

        return CopyDecision(
            skip=False,
            size=size,
            classification=classification,
            conviction=conviction,
            position=position,
        )

    def _normalize_market(self, market_name: str) -> str:
        """Normalize market name to a slug for grouping."""
        if not market_name:
            return "unknown"

        name_lower = market_name.lower()

        # Extract time component for 15-min markets
        time_match = re.search(r'(\d{1,2}):(\d{2})(am|pm)', name_lower)
        time_marker = ""
        if time_match:
            hour = int(time_match.group(1))
            minute = time_match.group(2)
            ampm = time_match.group(3)
            time_marker = f"_{hour}{ampm}"

        # Extract asset
        for asset in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "xrp"]:
            if asset in name_lower:
                asset_key = asset[:3] if len(asset) > 3 else asset
                return f"{asset_key}_updown{time_marker}"

        return name_lower.replace(" ", "_")[:30]

    def _calculate_conviction(
        self,
        trade_info,
        position: Optional[TargetPosition],
        classification: TradeClassification,
    ) -> ConvictionScore:
        """Calculate conviction score for a trade."""
        # Size percentile
        size_percentile = self._calculate_size_percentile(trade_info.size)

        # Scaling factor
        scaling_factor = 1.0
        if position:
            scaling_factor = position.scaling_factor

        # Time urgency (estimate based on 15-min markets)
        time_urgency = self._estimate_time_urgency(trade_info.market_name)

        # Major scale detection
        is_major_scale = classification == TradeClassification.MAJOR_SCALE

        return ConvictionScore(
            size_percentile=size_percentile,
            scaling_factor=scaling_factor,
            time_urgency=time_urgency,
            is_major_scale=is_major_scale,
            classification=classification,
        )

    def _calculate_size_percentile(self, size: float) -> float:
        """Calculate where this trade size ranks in historical sizes."""
        if len(self._trade_sizes) < 5:
            return 0.5  # Insufficient data

        sorted_sizes = sorted(self._trade_sizes)
        count_below = sum(1 for s in sorted_sizes if s < size)
        return count_below / len(sorted_sizes)

    def _estimate_time_urgency(self, market_name: str) -> float:
        """
        Estimate time urgency based on market name.
        For 15-min markets, this would ideally use the market's end time.
        Returns 0-1 where 1 is maximum urgency (market closing).
        """
        # For now, we can't determine exact market close time from name alone
        # In future, we could parse the market name or query the API
        # Default to moderate urgency
        return 0.3

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """Get all current positions as dictionaries."""
        return {
            slug: pos.to_dict()
            for slug, pos in self._position_tracker.get_all_positions().items()
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get intelligence system stats."""
        positions = self._position_tracker.get_all_positions()
        return {
            "enabled": self._enabled,
            "active_positions": len(positions),
            "trade_history_size": len(self._trade_sizes),
            "positions": self.get_positions(),
        }

    def reset(self) -> None:
        """Reset all state."""
        self._position_tracker.reset()
        self._trade_sizes.clear()
