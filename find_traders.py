"""Find profitable traders to copy on non-crypto markets."""
import requests
from collections import defaultdict

# Search for traders on high-volume markets
MARKETS = [
    "will-2025-be-the-hottest-year-on-record",
    "will-the-buffalo-bills-win-super-bowl-2026",
    "will-tariffs-generate-250b-in-2025",
]

print("=== SEARCHING FOR PROFITABLE TRADERS ===")
print()

# Method: Look at activity on multiple markets and find consistent traders
all_traders = defaultdict(lambda: {
    'volume': 0,
    'trades': 0,
    'markets': set(),
    'name': ''
})

for slug in MARKETS:
    url = f'https://gamma-api.polymarket.com/events?slug={slug}'
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            continue
        events = resp.json()
        if not events:
            continue

        event = events[0] if isinstance(events, list) else events
        markets = event.get('markets', [])

        for market in markets:
            cid = market.get('conditionId', '')
            if not cid:
                continue

            # Get trades for this market
            trades_url = f'https://data-api.polymarket.com/activity?conditionId={cid}&limit=50'
            trades_resp = requests.get(trades_url, timeout=10)
            trades_data = trades_resp.json()

            if not isinstance(trades_data, list):
                continue

            for t in trades_data:
                if not isinstance(t, dict):
                    continue
                if t.get('type', '').upper() != 'TRADE':
                    continue

                addr = t.get('proxyWallet', '')
                if not addr:
                    continue

                amount = float(t.get('usdcSize', 0) or 0)
                name = t.get('pseudonym', '') or t.get('name', '')

                all_traders[addr]['volume'] += amount
                all_traders[addr]['trades'] += 1
                all_traders[addr]['markets'].add(slug)
                if name:
                    all_traders[addr]['name'] = name

    except Exception as e:
        print(f"Error fetching {slug}: {e}")
        continue

# Sort by volume
sorted_traders = sorted(
    all_traders.items(),
    key=lambda x: x[1]['volume'],
    reverse=True
)

print("=== TOP ACTIVE TRADERS (by volume) ===")
print()

profitable_candidates = []

for addr, stats in sorted_traders[:15]:
    name = stats.get('name', '') or addr[:12]
    vol = stats.get('volume', 0)
    trades = stats.get('trades', 0)
    num_markets = len(stats.get('markets', set()))

    # Check their portfolio
    try:
        pos_url = f'https://data-api.polymarket.com/positions?user={addr}&sizeThreshold=0'
        pos_resp = requests.get(pos_url, timeout=10)
        positions = pos_resp.json()

        total_cost = 0
        total_value = 0

        for p in positions:
            if not isinstance(p, dict):
                continue
            size = float(p.get('size', 0) or 0)
            avg_price = float(p.get('avgPrice', 0) or 0)
            value = float(p.get('currentValue', 0) or 0)
            cost = size * avg_price
            total_cost += cost
            total_value += value

        pnl = total_value - total_cost
        roi = (pnl / total_cost * 100) if total_cost > 0 else 0

        print(f"{name}")
        print(f"  Address: {addr}")
        print(f"  Recent: {trades} trades, ${vol:.0f} volume, {num_markets} markets")
        print(f"  Portfolio: Cost ${total_cost:,.0f} | Value ${total_value:,.0f}")
        print(f"  PnL: ${pnl:+,.0f} ({roi:+.1f}%)")

        if roi > 5 and total_cost > 1000:
            profitable_candidates.append((addr, name, roi))
            print(f"  *** PROFITABLE CANDIDATE ***")
        print()

    except Exception as e:
        print(f"  Error checking portfolio: {e}")
        print()

print("=" * 60)
print("=== RECOMMENDED TRADERS TO COPY ===")
print()

if profitable_candidates:
    for addr, name, roi in sorted(profitable_candidates, key=lambda x: x[2], reverse=True):
        print(f"{name}: {addr}")
        print(f"  ROI: {roi:+.1f}%")
        print()
else:
    print("No profitable candidates found in this sample.")
    print("Try manually checking Polymarket leaderboard at https://polymarket.com/leaderboard")
