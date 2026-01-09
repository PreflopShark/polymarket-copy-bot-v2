"""
Pattern Analyzer for Copy Trading Bot

Automatically detects trading patterns from target trader:
- UP_BIAS: Trader is mostly buying UP outcomes
- DOWN_BIAS: Trader is mostly buying DOWN outcomes
- HEDGING: Trader is buying both sides of same market
- MIXED: No clear pattern
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum


class TradingPattern(str, Enum):
    """Detected trading patterns."""
    UP_BIAS = "up_bias"
    DOWN_BIAS = "down_bias"
    HEDGING = "hedging"
    MIXED = "mixed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class PatternConfig:
    """Configuration for pattern detection."""
    # Rolling window settings
    window_size: int = 20
    time_window_minutes: int = 30

    # Threshold settings
    bias_threshold: float = 0.65  # 65% in one direction = bias
    hedge_time_window_seconds: int = 300  # 5 minutes for hedge detection

    # Recency weighting
    recency_weight_decay: float = 0.9

    # Sensitivity
    min_trades_for_pattern: int = 5


@dataclass
class TradeRecord:
    """Record for pattern analysis."""
    timestamp: datetime
    market_slug: str
    condition_id: str
    outcome: str  # UP, DOWN, YES, NO
    side: str  # BUY, SELL
    size: float
    token_id: str


@dataclass
class PatternAnalysis:
    """Result of pattern analysis."""
    pattern: TradingPattern
    confidence: float
    up_ratio: float
    down_ratio: float
    hedge_pairs_detected: int
    recommended_filter: str  # "up", "down", "all", "skip_hedges"
    trades_analyzed: int
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


class MarketPositionTracker:
    """Tracks positions by market to detect hedging."""

    def __init__(self, config: PatternConfig):
        self._config = config
        # market_slug -> {outcome: [trade_records]}
        self._market_positions: Dict[str, Dict[str, List[TradeRecord]]] = {}
        self._hedge_pairs: List[Tuple[TradeRecord, TradeRecord]] = []

    def add_trade(self, trade: TradeRecord) -> Optional[TradeRecord]:
        """
        Add a trade and check if it forms a hedge pair.
        Returns the opposing trade if this forms a hedge, None otherwise.
        """
        market = trade.market_slug
        outcome = self._normalize_outcome(trade.outcome)
        opposite = self._get_opposite_outcome(outcome)

        if market not in self._market_positions:
            self._market_positions[market] = {}

        # Check if there's a recent opposing position
        if opposite and opposite in self._market_positions[market]:
            opposite_trades = self._market_positions[market][opposite]
            for opp_trade in reversed(opposite_trades):
                time_diff = (trade.timestamp - opp_trade.timestamp).total_seconds()
                if 0 <= time_diff <= self._config.hedge_time_window_seconds:
                    # This is a hedge!
                    self._hedge_pairs.append((opp_trade, trade))
                    return opp_trade

        # Add this trade to positions
        if outcome not in self._market_positions[market]:
            self._market_positions[market][outcome] = []
        self._market_positions[market][outcome].append(trade)

        return None

    def _normalize_outcome(self, outcome: str) -> str:
        """Normalize outcome to uppercase."""
        return outcome.upper() if outcome else ""

    def _get_opposite_outcome(self, outcome: str) -> str:
        """Get the opposite outcome."""
        opposites = {
            "UP": "DOWN", "DOWN": "UP",
            "YES": "NO", "NO": "YES",
        }
        return opposites.get(outcome.upper(), "")

    def is_hedge_trade(self, trade: TradeRecord) -> Tuple[bool, Optional[TradeRecord]]:
        """
        Check if this trade would complete a hedge.
        Returns (is_hedge, opposing_trade).
        """
        market = trade.market_slug
        outcome = self._normalize_outcome(trade.outcome)
        opposite = self._get_opposite_outcome(outcome)

        if not opposite or market not in self._market_positions:
            return False, None

        if opposite not in self._market_positions[market]:
            return False, None

        # Check for recent opposing position
        for opp_trade in reversed(self._market_positions[market][opposite]):
            time_diff = (trade.timestamp - opp_trade.timestamp).total_seconds()
            if 0 <= time_diff <= self._config.hedge_time_window_seconds:
                return True, opp_trade

        return False, None

    def get_hedge_count(self) -> int:
        """Get number of detected hedge pairs."""
        return len(self._hedge_pairs)

    def cleanup_old_positions(self, max_age_minutes: int = 60) -> None:
        """Remove positions older than max_age."""
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        for market in list(self._market_positions.keys()):
            for outcome in list(self._market_positions[market].keys()):
                self._market_positions[market][outcome] = [
                    t for t in self._market_positions[market][outcome]
                    if t.timestamp > cutoff
                ]
                # Clean up empty entries
                if not self._market_positions[market][outcome]:
                    del self._market_positions[market][outcome]
            if not self._market_positions[market]:
                del self._market_positions[market]

    def reset(self) -> None:
        """Reset all tracking."""
        self._market_positions.clear()
        self._hedge_pairs.clear()


class PatternAnalyzer:
    """
    Analyzes trading patterns from recent trades.

    Detects:
    - UP bias (mostly buying UP outcomes)
    - DOWN bias (mostly buying DOWN outcomes)
    - Hedging (buying both sides of same market)
    - Mixed (no clear pattern)
    """

    def __init__(self, config: Optional[PatternConfig] = None):
        self._config = config or PatternConfig()
        self._trade_buffer: List[TradeRecord] = []
        self._max_buffer_size = 100
        self._position_tracker = MarketPositionTracker(self._config)
        self._last_pattern: Optional[TradingPattern] = None
        self._pattern_history: List[Tuple[datetime, TradingPattern]] = []

    def add_trade(self, trade: TradeRecord) -> PatternAnalysis:
        """Add a trade and return updated pattern analysis."""
        # Add to buffer
        self._trade_buffer.append(trade)
        if len(self._trade_buffer) > self._max_buffer_size:
            self._trade_buffer.pop(0)

        # Track for hedge detection
        self._position_tracker.add_trade(trade)

        # Periodic cleanup
        if len(self._trade_buffer) % 20 == 0:
            self._position_tracker.cleanup_old_positions()

        # Analyze pattern
        return self.analyze()

    def add_trade_from_info(self, trade_info) -> PatternAnalysis:
        """Add a trade from TradeInfo dataclass."""
        record = TradeRecord(
            timestamp=datetime.fromtimestamp(trade_info.timestamp),
            market_slug=self._normalize_market(trade_info.market_name),
            condition_id=trade_info.condition_id or "",
            outcome=trade_info.outcome or "",
            side=trade_info.side,
            size=trade_info.size,
            token_id=trade_info.token_id,
        )
        return self.add_trade(record)

    def _normalize_market(self, market_name: str) -> str:
        """Normalize market name to a slug for comparison."""
        if not market_name:
            return "unknown"
        name_lower = market_name.lower()

        # Extract time component for 15-min markets
        # e.g., "Bitcoin Up or Down - January 8, 8:00PM-8:15PM ET"
        time_marker = ""
        if "8:00pm" in name_lower or "8:15pm" in name_lower:
            time_marker = "_8pm"
        elif "7:45pm" in name_lower or "8:00pm" in name_lower:
            time_marker = "_745pm"

        # Extract asset
        for asset in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "xrp"]:
            if asset in name_lower:
                asset_key = asset[:3] if len(asset) > 3 else asset
                return f"{asset_key}_updown{time_marker}"

        return name_lower.replace(" ", "_")[:30]

    def analyze(self) -> PatternAnalysis:
        """Analyze the current trade buffer for patterns."""
        window_trades = self._get_window_trades()

        if len(window_trades) < self._config.min_trades_for_pattern:
            return PatternAnalysis(
                pattern=TradingPattern.INSUFFICIENT_DATA,
                confidence=0.0,
                up_ratio=0.0,
                down_ratio=0.0,
                hedge_pairs_detected=0,
                recommended_filter="all",
                trades_analyzed=len(window_trades),
            )

        # Calculate weighted ratios
        up_count, down_count, total_weight = self._calculate_weighted_ratios(window_trades)

        up_ratio = up_count / total_weight if total_weight > 0 else 0
        down_ratio = down_count / total_weight if total_weight > 0 else 0

        # Check for hedging
        hedge_count = self._position_tracker.get_hedge_count()
        hedge_ratio = hedge_count / len(window_trades) if window_trades else 0

        # Determine pattern
        pattern, confidence, recommended = self._determine_pattern(
            up_ratio, down_ratio, hedge_ratio, len(window_trades)
        )

        analysis = PatternAnalysis(
            pattern=pattern,
            confidence=confidence,
            up_ratio=up_ratio,
            down_ratio=down_ratio,
            hedge_pairs_detected=hedge_count,
            recommended_filter=recommended,
            trades_analyzed=len(window_trades),
            window_start=window_trades[-1].timestamp if window_trades else None,
            window_end=window_trades[0].timestamp if window_trades else None,
        )

        # Track pattern changes
        if pattern != self._last_pattern and pattern != TradingPattern.INSUFFICIENT_DATA:
            self._pattern_history.append((datetime.now(), pattern))
            self._last_pattern = pattern

        return analysis

    def _get_window_trades(self) -> List[TradeRecord]:
        """Get trades within the analysis window."""
        trades = self._trade_buffer[-self._config.window_size:]

        # Optionally filter by time window
        if self._config.time_window_minutes > 0:
            cutoff = datetime.now() - timedelta(minutes=self._config.time_window_minutes)
            trades = [t for t in trades if t.timestamp > cutoff]

        return trades

    def _calculate_weighted_ratios(self, trades: List[TradeRecord]) -> Tuple[float, float, float]:
        """Calculate recency-weighted UP and DOWN ratios."""
        up_count = 0.0
        down_count = 0.0
        total_weight = 0.0

        for i, trade in enumerate(reversed(trades)):
            # More recent trades have higher weight
            weight = self._config.recency_weight_decay ** i

            outcome = (trade.outcome or "").upper()
            if outcome in ("UP", "YES"):
                up_count += weight
            elif outcome in ("DOWN", "NO"):
                down_count += weight

            total_weight += weight

        return up_count, down_count, total_weight

    def _determine_pattern(
        self,
        up_ratio: float,
        down_ratio: float,
        hedge_ratio: float,
        trade_count: int
    ) -> Tuple[TradingPattern, float, str]:
        """Determine the trading pattern from ratios."""

        # High hedge ratio indicates hedging mode
        if hedge_ratio > 0.3:
            return TradingPattern.HEDGING, hedge_ratio, "skip_hedges"

        # Check for directional bias
        bias_threshold = self._config.bias_threshold

        if up_ratio >= bias_threshold:
            confidence = min(1.0, (up_ratio - 0.5) * 2)
            return TradingPattern.UP_BIAS, confidence, "up"

        if down_ratio >= bias_threshold:
            confidence = min(1.0, (down_ratio - 0.5) * 2)
            return TradingPattern.DOWN_BIAS, confidence, "down"

        # Mixed pattern
        return TradingPattern.MIXED, 0.5, "all"

    def should_skip_trade(self, trade_info) -> Tuple[bool, str]:
        """
        Check if a trade should be skipped based on pattern analysis.
        Returns (should_skip, reason).
        """
        # Create a record for checking
        record = TradeRecord(
            timestamp=datetime.fromtimestamp(trade_info.timestamp),
            market_slug=self._normalize_market(trade_info.market_name),
            condition_id=trade_info.condition_id or "",
            outcome=trade_info.outcome or "",
            side=trade_info.side,
            size=trade_info.size,
            token_id=trade_info.token_id,
        )

        # First check if this is a hedge trade
        is_hedge, opposing = self._position_tracker.is_hedge_trade(record)
        if is_hedge:
            return True, f"Hedge detected - already have {opposing.outcome if opposing else 'opposite'} position"

        # Then check pattern-based filtering
        analysis = self.analyze()

        outcome = (trade_info.outcome or "").upper()

        if analysis.recommended_filter == "up" and outcome not in ("UP", "YES"):
            return True, f"Pattern: trader in UP mode ({analysis.up_ratio:.0%}), skipping {outcome}"

        if analysis.recommended_filter == "down" and outcome not in ("DOWN", "NO"):
            return True, f"Pattern: trader in DOWN mode ({analysis.down_ratio:.0%}), skipping {outcome}"

        return False, ""

    def get_current_pattern(self) -> PatternAnalysis:
        """Get the current pattern analysis."""
        return self.analyze()

    def get_pattern_history(self) -> List[Tuple[datetime, TradingPattern]]:
        """Get history of pattern changes."""
        return self._pattern_history.copy()

    def pattern_changed(self) -> bool:
        """Check if pattern changed on last analysis."""
        if len(self._pattern_history) < 2:
            return False
        return self._pattern_history[-1][1] != self._pattern_history[-2][1]

    def reset(self) -> None:
        """Reset analyzer state."""
        self._trade_buffer.clear()
        self._position_tracker.reset()
        self._last_pattern = None
        self._pattern_history.clear()
