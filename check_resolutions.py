"""
Resolve paper trading positions - check which markets have settled
"""
import json
import httpx
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"

def load_paper_trading(file_path: str) -> dict:
    with open(file_path, 'r') as f:
        return json.load(f)

def get_market_info(condition_id: str = None, slug: str = None) -> dict:
    """Get market info from Gamma API"""
    try:
        if slug:
            resp = httpx.get(f"{GAMMA_API}/markets", params={"slug": slug}, timeout=10.0)
        else:
            resp = httpx.get(f"{GAMMA_API}/markets", params={"limit": 200}, timeout=10.0)
        
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error: {e}")
    return []

def main():
    # Load latest paper trading file
    data = load_paper_trading("paper_trading_20260106_233556.json")
    
    print("=" * 70)
    print("PAPER TRADING RESOLUTION CHECK")
    print("=" * 70)
    print(f"Runtime: {data['summary']['runtime_hours']:.2f} hours")
    print(f"Trades copied: {data['summary']['trades_copied']}")
    print(f"Initial balance: ${data['summary']['initial_balance']:,.2f}")
    print(f"USDC spent: ${data['summary']['initial_balance'] - data['summary']['current_usdc']:,.2f}")
    print()
    
    # Get all markets to check resolution status
    all_markets = get_market_info()
    market_lookup = {}
    for m in all_markets:
        # Index by various keys
        title = m.get("question", m.get("title", ""))
        market_lookup[title] = m
        for t in m.get("tokens", []):
            market_lookup[t.get("token_id")] = m
    
    positions = data.get("positions", [])
    
    print(f"POSITIONS ({len(positions)}):")
    print("-" * 70)
    
    total_invested = 0
    total_pnl = 0
    resolved_count = 0
    
    for pos in positions:
        market_name = pos["market_name"]
        shares = pos["size"]
        entry_price = pos["entry_price"]
        usdc_spent = pos["usdc_spent"]
        total_invested += usdc_spent
        
        # Try to find market status
        market = market_lookup.get(pos.get("token_id")) or market_lookup.get(market_name)
        
        # Check if resolved by looking at market end time vs now
        # BTC Up/Down markets for specific times should be resolved if that time has passed
        
        # Parse market time from name
        is_resolved = False
        resolution = "?"
        pnl = 0
        
        # Example: "Bitcoin Up or Down - January 7, 2AM ET"
        if "January 7, 2AM" in market_name and "2:" not in market_name:
            # 2AM ET on Jan 7 = past (it's ~11:55PM on Jan 6)
            is_resolved = False  # Not yet
        elif "2:15AM" in market_name or "2:30AM" in market_name or "2:45AM" in market_name:
            is_resolved = False  # Not yet, these are future
        
        # For now, show current status
        if market:
            closed = market.get("closed", False)
            resolution_price = None
            
            # Check tokens for resolution
            for t in market.get("tokens", []):
                if t.get("token_id") == pos.get("token_id"):
                    # Winner price = 1.0, loser = 0.0
                    if market.get("resolved"):
                        resolution_price = 1.0 if t.get("winner") else 0.0
            
            if closed and resolution_price is not None:
                is_resolved = True
                pnl = shares * resolution_price - usdc_spent
                resolution = f"${resolution_price:.2f}"
                resolved_count += 1
        
        status = "✅ RESOLVED" if is_resolved else "⏳ PENDING"
        
        print(f"\n{market_name}")
        print(f"  Shares: {shares:.2f} @ ${entry_price:.4f}")
        print(f"  Invested: ${usdc_spent:.2f}")
        print(f"  Status: {status}")
        
        if is_resolved:
            print(f"  Resolution: {resolution}")
            print(f"  P&L: ${pnl:+.2f}")
            total_pnl += pnl
    
    print()
    print("=" * 70)
    print(f"SUMMARY")
    print("=" * 70)
    print(f"Total invested: ${total_invested:.2f}")
    print(f"Resolved: {resolved_count}/{len(positions)}")
    print(f"Realized P&L: ${total_pnl:+.2f}")
    print()
    print("Note: Most positions are for future times (2AM+) - not resolved yet.")
    print("The trader is trading BTC Up/Down 15-min markets expiring in a few hours.")

if __name__ == "__main__":
    main()
