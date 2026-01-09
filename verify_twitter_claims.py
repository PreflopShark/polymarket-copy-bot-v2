"""
Verify Twitter claims about target trader @0x8dxd (0x63ce...)

Claims to verify:
1. Trades BTC/ETH/SOL 15-minute Up/Down markets only
2. Over 6,300 bets since early December
3. 98% win rate
4. $4-5k bet every time
5. Uses directional (temporal arbitrage) not paired arb
"""

import asyncio
import aiohttp
from collections import defaultdict
from datetime import datetime, timedelta

TARGET_ADDRESS = "0x63ce342161250d705dc0b16df89036c8e5f9ba9a"

async def fetch_all_activity():
    """Fetch all trader activity"""
    all_trades = []
    offset = 0
    limit = 500
    
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://data-api.polymarket.com/activity?user={TARGET_ADDRESS}&limit={limit}&offset={offset}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"Error fetching: {resp.status}")
                    break
                data = await resp.json()
                if not data:
                    break
                all_trades.extend(data)
                print(f"Fetched {len(all_trades)} trades so far...")
                if len(data) < limit:
                    break
                offset += limit
    
    return all_trades

def analyze_trades(trades):
    print("\n" + "="*60)
    print("TARGET TRADER ANALYSIS")
    print("="*60)
    
    # Basic counts
    print(f"\nTotal trades fetched: {len(trades)}")
    
    if not trades:
        print("No trades found!")
        return
    
    # Parse timestamps
    timestamps = []
    for t in trades:
        try:
            ts = datetime.fromisoformat(t.get('timestamp', '').replace('Z', '+00:00'))
            timestamps.append(ts)
        except:
            pass
    
    if timestamps:
        oldest = min(timestamps)
        newest = max(timestamps)
        print(f"Date range: {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')}")
        days = (newest - oldest).days + 1
        print(f"Days active: {days}")
        print(f"Avg trades per day: {len(trades)/days:.1f}")
    
    # ===== CLAIM 1: BTC/ETH/SOL 15-min markets only? =====
    print("\n" + "-"*60)
    print("CLAIM 1: Trades BTC/ETH/SOL 15-minute Up/Down markets only")
    print("-"*60)
    
    market_titles = defaultdict(int)
    crypto_15min = 0
    other_markets = 0
    
    for t in trades:
        title = t.get('title', 'Unknown')
        market_titles[title] += 1
        
        title_lower = title.lower()
        is_crypto = any(x in title_lower for x in ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol'])
        is_15min = '15' in title_lower or 'up or down' in title_lower
        
        if is_crypto and is_15min:
            crypto_15min += 1
        else:
            other_markets += 1
    
    print(f"Crypto 15-min markets: {crypto_15min} trades ({100*crypto_15min/len(trades):.1f}%)")
    print(f"Other markets: {other_markets} trades ({100*other_markets/len(trades):.1f}%)")
    
    print("\nTop 10 markets by trade count:")
    for title, count in sorted(market_titles.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count:4d}x - {title[:70]}")
    
    # ===== CLAIM 2: 6,300+ bets since early December =====
    print("\n" + "-"*60)
    print("CLAIM 2: Over 6,300 bets since early December")
    print("-"*60)
    print(f"Total trades in API: {len(trades)}")
    
    dec_trades = [t for t in trades if 'timestamp' in t and '2024-12' in t['timestamp'] or '2025-' in t.get('timestamp', '')]
    print(f"Trades since Dec 2024: ~{len(dec_trades)}")
    
    # ===== CLAIM 3: 98% win rate =====
    print("\n" + "-"*60)
    print("CLAIM 3: 98% win rate")
    print("-"*60)
    
    buys = [t for t in trades if t.get('side') == 'buy']
    sells = [t for t in trades if t.get('side') == 'sell']
    print(f"Buy trades: {len(buys)}")
    print(f"Sell trades: {len(sells)}")
    
    # Check outcomes for sells
    winning_sells = 0
    losing_sells = 0
    for t in sells:
        price = float(t.get('price', 0))
        if price > 0.5:
            winning_sells += 1
        else:
            losing_sells += 1
    
    if sells:
        print(f"Sells at >$0.50 (likely wins): {winning_sells} ({100*winning_sells/len(sells):.1f}%)")
        print(f"Sells at <$0.50 (likely losses): {losing_sells} ({100*losing_sells/len(sells):.1f}%)")
    
    # ===== CLAIM 4: $4-5k bet every time =====
    print("\n" + "-"*60)
    print("CLAIM 4: $4-5k bet every time")
    print("-"*60)
    
    sizes = []
    for t in trades:
        try:
            size = float(t.get('usdcSize', 0))
            if size > 0:
                sizes.append(size)
        except:
            pass
    
    if sizes:
        avg_size = sum(sizes) / len(sizes)
        median_size = sorted(sizes)[len(sizes)//2]
        max_size = max(sizes)
        min_size = min(sizes)
        
        print(f"Average trade size: ${avg_size:.2f}")
        print(f"Median trade size: ${median_size:.2f}")
        print(f"Range: ${min_size:.2f} - ${max_size:.2f}")
        
        # Distribution
        under_100 = sum(1 for s in sizes if s < 100)
        s100_500 = sum(1 for s in sizes if 100 <= s < 500)
        s500_1000 = sum(1 for s in sizes if 500 <= s < 1000)
        s1000_5000 = sum(1 for s in sizes if 1000 <= s < 5000)
        s4000_5000 = sum(1 for s in sizes if 4000 <= s <= 5000)
        over_5000 = sum(1 for s in sizes if s >= 5000)
        
        print(f"\nSize distribution:")
        print(f"  Under $100: {under_100} ({100*under_100/len(sizes):.1f}%)")
        print(f"  $100-$500: {s100_500} ({100*s100_500/len(sizes):.1f}%)")
        print(f"  $500-$1000: {s500_1000} ({100*s500_1000/len(sizes):.1f}%)")
        print(f"  $1000-$5000: {s1000_5000} ({100*s1000_5000/len(sizes):.1f}%)")
        print(f"  $4000-$5000 (claimed range): {s4000_5000} ({100*s4000_5000/len(sizes):.1f}%)")
        print(f"  $5000+: {over_5000} ({100*over_5000/len(sizes):.1f}%)")
    
    # ===== CLAIM 5: Directional not paired =====
    print("\n" + "-"*60)
    print("CLAIM 5: Directional (temporal arb) not paired arb")
    print("-"*60)
    
    # Group by market/conditionId
    by_market = defaultdict(lambda: {'buys': [], 'outcomes': set()})
    for t in trades:
        cond = t.get('conditionId', t.get('title', 'unknown'))
        outcome = t.get('outcome', 'unknown')
        side = t.get('side', 'unknown')
        by_market[cond]['outcomes'].add(outcome)
        if side == 'buy':
            by_market[cond]['buys'].append(t)
    
    single_side = 0
    both_sides = 0
    
    for market, data in by_market.items():
        if len(data['outcomes']) == 1:
            single_side += 1
        else:
            both_sides += 1
    
    print(f"Markets with single outcome bet: {single_side}")
    print(f"Markets with both outcomes bet: {both_sides}")
    
    if single_side + both_sides > 0:
        pct_directional = 100 * single_side / (single_side + both_sides)
        print(f"% Directional: {pct_directional:.1f}%")
    
    # Sample recent trades
    print("\n" + "-"*60)
    print("SAMPLE RECENT TRADES")
    print("-"*60)
    
    for t in trades[:15]:
        side = t.get('side', '?')
        size = t.get('usdcSize', 0)
        price = t.get('price', 0)
        title = t.get('title', 'Unknown')[:50]
        outcome = t.get('outcome', '?')
        ts = t.get('timestamp', '')[:19]
        print(f"{ts} | {side.upper():4} ${float(size):7.2f} @ {float(price):.2f} | {outcome[:10]:10} | {title}")

if __name__ == "__main__":
    print("Fetching trader activity...")
    trades = asyncio.run(fetch_all_activity())
    analyze_trades(trades)
