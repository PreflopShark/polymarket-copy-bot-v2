"""Proper analysis of target trader's performance vs our execution."""

import requests
from datetime import datetime, timedelta
from collections import defaultdict
import json

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
OUR_PROXY = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'

print("="*70)
print("COMPREHENSIVE TRADE ANALYSIS")
print("="*70)

# Fetch target's recent activity
url = f'https://data-api.polymarket.com/activity?user={TARGET}&limit=500'
print(f'\n1. Fetching target trader activity...')
resp = requests.get(url, timeout=60)
target_activities = resp.json()
print(f'   Retrieved {len(target_activities)} activities')

# Filter to TRADE type only
target_trades = [t for t in target_activities if t.get('type', '').upper() == 'TRADE']
print(f'   {len(target_trades)} are actual trades')

# Get time range
cutoff = datetime.now() - timedelta(hours=6)

recent_trades = []
for t in target_trades:
    ts_val = t.get('timestamp', 0)
    if isinstance(ts_val, int):
        ts = datetime.fromtimestamp(ts_val)
        if ts >= cutoff:
            t['_datetime'] = ts
            recent_trades.append(t)

print(f'   {len(recent_trades)} trades in last 6 hours')

# Group by market AND outcome (condition_id + outcome_index)
positions = defaultdict(lambda: {
    'buys': [],
    'sells': [],
    'title': '',
    'outcome': '',
    'asset': '',
    'condition_id': '',
    'outcome_index': 0,
})

for t in recent_trades:
    cond_id = t.get('conditionId', '')
    outcome_idx = t.get('outcomeIndex', 0)
    key = (cond_id, outcome_idx)
    
    positions[key]['title'] = t.get('title', 'Unknown')
    positions[key]['outcome'] = t.get('outcome', f'outcome_{outcome_idx}')
    positions[key]['asset'] = t.get('asset', '')
    positions[key]['condition_id'] = cond_id
    positions[key]['outcome_index'] = outcome_idx
    
    if t.get('side') == 'BUY':
        positions[key]['buys'].append({
            'price': float(t.get('price', 0)),
            'size': float(t.get('usdcSize', 0)),
            'shares': float(t.get('size', 0)),
            'time': t['_datetime'],
        })
    else:
        positions[key]['sells'].append({
            'price': float(t.get('price', 0)),
            'size': float(t.get('usdcSize', 0)),
            'shares': float(t.get('size', 0)),
            'time': t['_datetime'],
        })

print(f'\n2. Analyzing {len(positions)} unique positions...')

# Now analyze each position properly
results = []

for key, pos in positions.items():
    if not pos['buys']:
        continue
    
    title = pos['title'][:50]
    outcome = pos['outcome']
    asset = pos['asset']
    
    # Calculate cost basis
    total_cost = sum(b['size'] for b in pos['buys'])
    total_shares_bought = sum(b['shares'] for b in pos['buys'])
    avg_buy_price = total_cost / total_shares_bought if total_shares_bought > 0 else 0
    
    # Calculate sells
    total_sell_proceeds = sum(s['size'] for s in pos['sells'])
    total_shares_sold = sum(s['shares'] for s in pos['sells'])
    
    # Net position
    net_shares = total_shares_bought - total_shares_sold
    
    # Get CURRENT price for THIS specific token
    current_price = None
    try:
        book_url = f'https://clob.polymarket.com/book?token_id={asset}'
        book_resp = requests.get(book_url, timeout=5)
        book = book_resp.json()
        
        # For the price, we want the bid (what we could sell at)
        if book.get('bids') and len(book['bids']) > 0:
            current_price = float(book['bids'][0]['price'])
        elif book.get('asks') and len(book['asks']) > 0:
            current_price = float(book['asks'][0]['price'])
    except Exception as e:
        pass
    
    # Determine if resolved
    is_resolved = False
    resolution_value = None
    
    if current_price is not None:
        if current_price >= 0.98:
            is_resolved = True
            resolution_value = 1.0  # This outcome won
        elif current_price <= 0.02:
            is_resolved = True
            resolution_value = 0.0  # This outcome lost
    
    # Calculate P&L
    if is_resolved:
        # Final P&L = (resolution_value * shares) - cost + sell_proceeds
        final_value = resolution_value * total_shares_bought
        realized_pnl = final_value - total_cost + total_sell_proceeds
        pnl_pct = (realized_pnl / total_cost * 100) if total_cost > 0 else 0
        status = 'WON' if resolution_value == 1.0 else 'LOST'
    else:
        # Unrealized P&L
        if current_price and net_shares > 0:
            current_value = net_shares * current_price
            unrealized_cost = total_cost - total_sell_proceeds
            realized_pnl = current_value - (avg_buy_price * net_shares)
            pnl_pct = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0
            status = 'OPEN'
        else:
            realized_pnl = 0
            pnl_pct = 0
            status = 'CLOSED'
    
    results.append({
        'title': title,
        'outcome': outcome,
        'status': status,
        'avg_buy': avg_buy_price,
        'current': current_price,
        'cost': total_cost,
        'shares': total_shares_bought,
        'net_shares': net_shares,
        'pnl': realized_pnl,
        'pnl_pct': pnl_pct,
    })

# Print results
print("\n" + "="*70)
print("TARGET TRADER POSITION ANALYSIS (Last 6 Hours)")
print("="*70)

won = [r for r in results if r['status'] == 'WON']
lost = [r for r in results if r['status'] == 'LOST']
open_pos = [r for r in results if r['status'] == 'OPEN']
closed = [r for r in results if r['status'] == 'CLOSED']

print(f"\nResolved Positions: {len(won)} WON, {len(lost)} LOST")
print(f"Open Positions: {len(open_pos)}")
print(f"Closed (sold out): {len(closed)}")

if won or lost:
    win_rate = len(won) / (len(won) + len(lost)) * 100
    print(f"Resolution Win Rate: {win_rate:.1f}%")

print("\n--- WINNING POSITIONS ---")
total_won = 0
for r in sorted(won, key=lambda x: -x['pnl']):
    print(f"  {r['title']}")
    print(f"    {r['outcome']} @ {r['avg_buy']:.1%} -> WON | Cost: ${r['cost']:.2f} | P&L: ${r['pnl']:.2f} ({r['pnl_pct']:+.1f}%)")
    total_won += r['pnl']

print(f"\n  Total Won: ${total_won:.2f}")

print("\n--- LOSING POSITIONS ---")
total_lost = 0
for r in sorted(lost, key=lambda x: x['pnl']):
    print(f"  {r['title']}")
    print(f"    {r['outcome']} @ {r['avg_buy']:.1%} -> LOST | Cost: ${r['cost']:.2f} | P&L: ${r['pnl']:.2f}")
    total_lost += abs(r['pnl'])

print(f"\n  Total Lost: ${total_lost:.2f}")

print("\n--- OPEN POSITIONS ---")
total_unrealized = 0
for r in sorted(open_pos, key=lambda x: -x['pnl_pct']):
    cur = r['current'] if r['current'] else 0
    print(f"  {r['title']}")
    print(f"    {r['outcome']} @ {r['avg_buy']:.1%} -> Now {cur:.1%} | Cost: ${r['cost']:.2f} | Unrealized: {r['pnl_pct']:+.1f}%")
    total_unrealized += r['pnl']

print(f"\n  Total Unrealized P&L: ${total_unrealized:.2f}")

print("\n" + "="*70)
print("NET PERFORMANCE SUMMARY")
print("="*70)
net_realized = total_won - total_lost
print(f"Realized P&L (resolved): ${net_realized:.2f}")
print(f"Unrealized P&L (open): ${total_unrealized:.2f}")
print(f"Total P&L: ${net_realized + total_unrealized:.2f}")

# Now compare with OUR trades
print("\n" + "="*70)
print("OUR BOT'S EXECUTION COMPARISON")
print("="*70)

url = f'https://data-api.polymarket.com/activity?user={OUR_PROXY}&limit=500'
print(f'\nFetching our activity...')
resp = requests.get(url, timeout=60)
our_activities = resp.json()
our_trades = [t for t in our_activities if t.get('type', '').upper() == 'TRADE']
print(f'Retrieved {len(our_trades)} trades')

# Group our trades
our_positions = defaultdict(lambda: {
    'buys': [],
    'sells': [],
    'title': '',
    'outcome': '',
    'asset': '',
})

for t in our_trades:
    cond_id = t.get('conditionId', '')
    outcome_idx = t.get('outcomeIndex', 0)
    key = (cond_id, outcome_idx)
    
    our_positions[key]['title'] = t.get('title', 'Unknown')
    our_positions[key]['outcome'] = t.get('outcome', f'outcome_{outcome_idx}')
    our_positions[key]['asset'] = t.get('asset', '')
    
    if t.get('side') == 'BUY':
        our_positions[key]['buys'].append({
            'price': float(t.get('price', 0)),
            'size': float(t.get('usdcSize', 0)),
            'shares': float(t.get('size', 0)),
        })

# Compare what target traded vs what we traded
target_markets = set(positions.keys())
our_markets = set(our_positions.keys())

copied = target_markets & our_markets
missed = target_markets - our_markets

print(f"\nTarget traded {len(target_markets)} positions")
print(f"We traded {len(our_markets)} positions")
print(f"We copied {len(copied)} of target's positions")
print(f"We missed {len(missed)} of target's positions")

# Analyze what we missed
print("\n--- POSITIONS WE MISSED ---")
for key in missed:
    pos = positions[key]
    if not pos['buys']:
        continue
    
    total_cost = sum(b['size'] for b in pos['buys'])
    result = next((r for r in results if r['title'] == pos['title'][:50] and r['outcome'] == pos['outcome']), None)
    
    if result:
        status = result['status']
        pnl = result['pnl']
        print(f"  {pos['title'][:50]}")
        print(f"    {pos['outcome']} | Target cost: ${total_cost:.2f} | Result: {status} (P&L: ${pnl:.2f})")
