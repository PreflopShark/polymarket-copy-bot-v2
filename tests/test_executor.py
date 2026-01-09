"""Unit tests for TradeExecutor to verify no execution bugs."""

import pytest
import asyncio
import sys
import os

# Add project root to path so we can import src as a package
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.executor import TradeExecutor, BUY, SELL


class MockConfig:
    """Mock configuration for testing."""
    def __init__(self):
        # Core sizing
        self.copy_ratio = 0.1
        self.min_trade_amount = 1.0
        self.max_trade_amount = 100.0
        self.min_target_trade = 0.0

        # Mode
        self.dry_run = True
        self.initial_paper_balance = 1000.0

        # Execution controls (match defaults in src.config.Config)
        self.stale_order_timeout = 0.5
        self.max_slippage_percent = 15.0
        self.max_hedge_imbalance_percent = 30.0
        self.skip_opposite_side = True

        # Strategy price filters
        self.max_price = 0.85
        self.min_price = 0.15

        # Conviction scaling defaults
        self.high_conviction_threshold = 200.0
        self.high_conviction_ratio = 0.20
        self.low_conviction_ratio = 0.03

        # Per-asset ratios
        self.btc_copy_ratio = 0.02
        self.eth_copy_ratio = 0.03
        self.sol_copy_ratio = 0.04

        # Display
        self.market_name_max_len = 40

    def get_copy_ratio_for_asset(self, asset_code: str) -> float:
        ratios = {
            "BTC": self.btc_copy_ratio,
            "ETH": self.eth_copy_ratio,
            "SOL": self.sol_copy_ratio,
        }
        return ratios.get(asset_code, self.low_conviction_ratio)


class TestDuplicateDetection:
    """Test duplicate trade detection."""

    def test_first_trade_not_duplicate(self):
        """First occurrence of a trade should not be detected as duplicate."""
        executor = TradeExecutor(None, MockConfig())
        activity = {"transactionHash": "0xabc123", "type": "TRADE"}

        assert executor.is_duplicate_trade(activity) is False

    def test_second_trade_is_duplicate(self):
        """Second occurrence of same transaction should be detected as duplicate."""
        executor = TradeExecutor(None, MockConfig())
        activity = {"transactionHash": "0xabc123", "type": "TRADE"}

        # First time - not duplicate
        executor.mark_trade_processed(activity)

        # Second time - should be duplicate
        assert executor.is_duplicate_trade(activity) is True

    def test_different_trades_not_duplicate(self):
        """Different transactions should not be detected as duplicates."""
        executor = TradeExecutor(None, MockConfig())
        activity1 = {"transactionHash": "0xabc123", "type": "TRADE"}
        activity2 = {"transactionHash": "0xdef456", "type": "TRADE"}

        executor.mark_trade_processed(activity1)

        assert executor.is_duplicate_trade(activity2) is False

    def test_no_hash_not_duplicate(self):
        """Activity without transaction hash should not be detected as duplicate."""
        executor = TradeExecutor(None, MockConfig())
        activity = {"type": "TRADE"}  # No transactionHash

        assert executor.is_duplicate_trade(activity) is False

    def test_duplicate_set_size_limit(self):
        """Test that duplicate detection set doesn't grow unbounded."""
        executor = TradeExecutor(None, MockConfig())

        # Add 1100 trades
        for i in range(1100):
            activity = {"transactionHash": f"0x{i:064x}", "type": "TRADE"}
            executor.mark_trade_processed(activity)

        # Set should be trimmed to ~1000 (FIFO eviction)
        assert len(executor.processed_trades) <= 1001


class TestActivityFiltering:
    """Test that non-TRADE activities are filtered."""

    def test_trade_activity_processed(self):
        """TRADE activities should be processed."""
        executor = TradeExecutor(None, MockConfig())
        activity = {
            "type": "TRADE",
            "transactionHash": "0xabc123",
            "asset": "12345",
            "side": "BUY",
            "usdcSize": 10.0,
            "price": 0.5,
            "title": "Test Market",
            "conditionId": "cond123",
            "outcomeIndex": 0,
            "outcome": "YES",
            "size": 20.0,
        }

        trade = executor.parse_trade_activity(activity)
        assert trade is not None
        assert trade["side"] == BUY

    def test_redeem_activity_filtered(self):
        """REDEEM activities should be filtered out."""
        executor = TradeExecutor(None, MockConfig())
        activity = {
            "type": "REDEEM",
            "transactionHash": "0xabc123",
            "usdcSize": 100.0
        }

        trade = executor.parse_trade_activity(activity)
        assert trade is None

    def test_transfer_activity_filtered(self):
        """TRANSFER activities should be filtered out."""
        executor = TradeExecutor(None, MockConfig())
        activity = {
            "type": "TRANSFER",
            "transactionHash": "0xabc123",
            "usdcSize": 50.0
        }

        trade = executor.parse_trade_activity(activity)
        assert trade is None


class TestTradeSizeCalculation:
    """Test trade size calculation with copy ratio and limits."""

    def test_normal_scaling(self):
        """Test normal trade scaling at 10% ratio."""
        executor = TradeExecutor(None, MockConfig())

        # $100 trade at 10% = $10
        size = executor.calculate_trade_size(100.0)
        assert size == 10.0

    def test_minimum_enforcement(self):
        """Test that minimum trade amount is enforced."""
        executor = TradeExecutor(None, MockConfig())

        # $5 trade at 10% = $0.50, should be bumped to $1.00 minimum
        size = executor.calculate_trade_size(5.0)
        assert size == 1.0

    def test_maximum_enforcement(self):
        """Test that maximum trade amount is enforced."""
        executor = TradeExecutor(None, MockConfig())

        # $2000 trade at 10% = $200, should be capped at $100 maximum
        size = executor.calculate_trade_size(2000.0)
        assert size == 100.0


class TestPositionTracking:
    """Test position tracking for exit copying."""

    def test_new_position_created(self):
        """Test that buying creates a new position."""
        executor = TradeExecutor(None, MockConfig())

        executor.update_position(
            token_id="token123",
            side=BUY,
            size=10.0,  # $10 USDC
            price=0.5,  # $0.50 per share
            market_name="Test Market"
        )

        assert "token123" in executor.positions
        assert executor.positions["token123"]["shares"] == 20.0  # 10/0.5 = 20 shares
        assert executor.positions["token123"]["cost_basis"] == 10.0

    def test_position_increased(self):
        """Test that additional buys increase position."""
        executor = TradeExecutor(None, MockConfig())

        # First buy: 20 shares
        executor.update_position("token123", BUY, 10.0, 0.5, "Test Market")
        # Second buy: 10 shares
        executor.update_position("token123", BUY, 5.0, 0.5, "Test Market")

        assert executor.positions["token123"]["shares"] == 30.0
        assert executor.positions["token123"]["cost_basis"] == 15.0

    def test_position_reduced_on_sell(self):
        """Test that selling reduces position."""
        executor = TradeExecutor(None, MockConfig())

        # Buy 20 shares
        executor.update_position("token123", BUY, 10.0, 0.5, "Test Market")
        # Sell 10 shares
        executor.update_position("token123", SELL, 5.0, 0.5, "Test Market")

        assert executor.positions["token123"]["shares"] == 10.0
        assert executor.positions["token123"]["cost_basis"] == 5.0

    def test_position_closed_on_full_sell(self):
        """Test that position is removed when fully sold."""
        executor = TradeExecutor(None, MockConfig())

        # Buy 20 shares
        executor.update_position("token123", BUY, 10.0, 0.5, "Test Market")
        # Sell all 20 shares
        executor.update_position("token123", SELL, 10.0, 0.5, "Test Market")

        assert "token123" not in executor.positions


class TestExitCopying:
    """Test exit copying logic."""

    def test_sell_without_position_skipped(self):
        """Test that SELL without position does not execute."""
        executor = TradeExecutor(None, MockConfig())

        activity = {
            "type": "TRADE",
            "transactionHash": "0xsell123",
            "asset": "token_we_dont_own",
            "side": "SELL",
            "usdcSize": 50.0,
            "price": 0.6,
            "title": "Market We Don't Own",
            # Include conditionId so the directional strategy accepts the trade object
            "conditionId": "cond123",
            "outcomeIndex": 0,
            "outcome": "YES",
            "size": 10.0,
        }

        result = asyncio.run(executor.copy_trade(activity))
        assert result is not None
        assert result.get("status") == "skipped"
        assert result.get("result") is not None
        assert result["result"].get("status") == "skipped"
        assert result["result"].get("reason") == "no_position_to_sell"

    def test_sell_with_position_processed(self):
        """Test that SELL is processed if we hold the position."""
        config = MockConfig()
        config.dry_run = True

        executor = TradeExecutor(None, config)

        # First, create a position
        executor.positions["token123"] = {
            "side": BUY,
            "shares": 100.0,
            "cost_basis": 50.0,
            "market_name": "Test Market"
        }

        activity = {
            "type": "TRADE",
            "transactionHash": "0xsell456",
            "asset": "token123",
            "side": "SELL",
            "usdcSize": 30.0,
            "price": 0.6,
            "title": "Test Market",
            "conditionId": "cond123",
            "outcomeIndex": 0,
            "outcome": "YES",
            "size": 50.0,
        }

        # In dry run mode, this should return a result
        result = asyncio.run(executor.copy_trade(activity))
        assert result is not None


class TestNoDuplicateExecution:
    """Integration tests to ensure no duplicate executions."""

    def test_same_trade_not_executed_twice(self):
        """Ensure the same trade is not executed twice."""
        async def run_test():
            config = MockConfig()
            config.dry_run = True

            executor = TradeExecutor(None, config)

            activity = {
                "type": "TRADE",
                "transactionHash": "0xunique123",
                "asset": "token123",
                "side": "BUY",
                "usdcSize": 20.0,
                "price": 0.5,
                "title": "Test Market",
                "conditionId": "cond123",
                "outcomeIndex": 0,
                "outcome": "YES",
                "size": 40.0,
            }

            # First execution should succeed
            result1 = await executor.copy_trade(activity)
            assert result1 is not None

            # Second execution of same trade should be skipped
            result2 = await executor.copy_trade(activity)
            assert result2 is None

        asyncio.run(run_test())

    def test_rapid_same_trades_deduplicated(self):
        """Simulate rapid duplicate trades (like API returning same trade twice)."""
        async def run_test():
            config = MockConfig()
            config.dry_run = True

            executor = TradeExecutor(None, config)

            # Same transaction hash (simulating API quirk)
            activities = [
                {
                    "type": "TRADE",
                    "transactionHash": "0xrapid123",
                    "asset": "token123",
                    "side": "BUY",
                    "usdcSize": 10.0,
                    "price": 0.5,
                    "title": "Test Market",
                    "conditionId": "cond123",
                    "outcomeIndex": 0,
                    "outcome": "YES",
                    "size": 20.0,
                }
                for _ in range(5)  # 5 "duplicate" activities
            ]

            results = []
            for activity in activities:
                result = await executor.copy_trade(activity)
                results.append(result)

            # Only first one should succeed
            successful = [r for r in results if r is not None]
            assert len(successful) == 1

        asyncio.run(run_test())


class TestShareCalculation:
    """Test share calculation for orders."""

    def test_usdc_to_shares_conversion(self):
        """Test that USDC is correctly converted to shares."""
        # $10 at $0.50 per share = 20 shares
        usdc = 10.0
        price = 0.5
        shares = usdc / price
        assert shares == 20.0

    def test_minimum_share_enforcement(self):
        """Test that minimum 5 shares is enforced."""
        # $1 at $0.50 per share = 2 shares (below minimum)
        usdc = 1.0
        price = 0.5
        shares = usdc / price

        if shares < 5:
            shares = 5
            usdc = shares * price

        assert shares == 5
        assert usdc == 2.5  # 5 shares * $0.50


def run_tests():
    """Run all tests and return results."""
    import io
    import contextlib

    # Capture output
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        with contextlib.redirect_stderr(output):
            # Run pytest
            exit_code = pytest.main([
                __file__,
                "-v",
                "--tb=short",
                "-q"
            ])

    return exit_code, output.getvalue()


if __name__ == "__main__":
    exit_code, output = run_tests()
    print(output)
    sys.exit(exit_code)
