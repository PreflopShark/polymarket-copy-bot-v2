"""Abstract interfaces for dependency injection and testing."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class TradeInfo:
    """Standardized trade information."""
    token_id: str
    market_name: str
    side: str  # BUY or SELL
    outcome: str
    price: float
    size: float
    tx_hash: str
    timestamp: float
    condition_id: Optional[str] = None
    outcome_index: Optional[int] = None

    @classmethod
    def from_activity(cls, activity: dict) -> "TradeInfo":
        """Create TradeInfo from Polymarket activity data."""
        return cls(
            token_id=str(activity.get("asset", "")),
            market_name=activity.get("title", "Unknown")[:50],
            side=activity.get("side", "").upper(),
            outcome=activity.get("outcome", ""),
            price=float(activity.get("price", 0)),
            size=float(activity.get("usdcSize", 0)),
            tx_hash=activity.get("transactionHash", ""),
            timestamp=float(activity.get("timestamp", 0)),
            condition_id=activity.get("conditionId"),
            outcome_index=activity.get("outcomeIndex"),
        )


@dataclass
class OrderBookInfo:
    """Order book information."""
    best_bid: Optional[float]
    best_ask: Optional[float]
    bid_depth: float
    ask_depth: float


@dataclass
class ExecutionResult:
    """Result of trade execution."""
    success: bool
    status: str  # matched, skipped, failed, paper_trade
    message: str
    price: Optional[float] = None
    size: Optional[float] = None
    shares: Optional[float] = None
    reason: Optional[str] = None


class TradingClient(ABC):
    """Abstract interface for trading operations."""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the trading platform."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the trading platform."""
        pass

    @abstractmethod
    def get_balance(self) -> Optional[float]:
        """Get current USDC balance."""
        pass

    @abstractmethod
    def get_order_book(self, token_id: str) -> Optional[OrderBookInfo]:
        """Get order book for a token."""
        pass

    @abstractmethod
    async def execute_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> ExecutionResult:
        """Execute a trade order."""
        pass


class TradeMonitor(ABC):
    """Abstract interface for monitoring trades."""

    @abstractmethod
    async def fetch_trades(self) -> List[Dict[str, Any]]:
        """Fetch recent trades from target."""
        pass

    @abstractmethod
    def filter_new_trades(self, trades: List[Dict]) -> List[Dict]:
        """Filter out already-seen trades."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset monitor state."""
        pass


class TradeExecutor(ABC):
    """Abstract interface for trade execution strategy."""

    @abstractmethod
    async def evaluate(self, trade: TradeInfo) -> Optional[Dict[str, Any]]:
        """Evaluate whether to copy a trade."""
        pass

    @abstractmethod
    async def execute(self, trade: TradeInfo, decision: Dict) -> ExecutionResult:
        """Execute the trade based on decision."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        pass
