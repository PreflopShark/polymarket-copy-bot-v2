"""Analyze target trader performance vs our bot's execution."""

import requests
from datetime import datetime, timedelta
from collections import defaultdict
import json

# Get target's trades from last 6 hours
TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
cutoff = datetime.now() - timedelta(hours=6)

url = f'https://data-api.polymarket.com/activity?user={TARGET}&limit=500'
print(f'Fetching target trades...')
resp = requests.get(url, timeout=30)
all_trades = resp.json()

# Filter to last 6 hours and TRADE type
trades = []
for t in all_trades:
    if t.get('type', '').upper() != 'TRADE':
        continue
    ts_val = t.get('timestamp', 0)
    if isinstance(ts_val, int):
        ts = datetime.fromtimestamp(ts_val)
    else:
        ts = datetime.fromisoformat(str(ts_val).replace('Z', '+00:00')).replace(tzinfo=None)
    if ts >= cutoff:
        t['_datetime'] = ts
        trades.append(t)

print(f'Found {len(trades)} trades in last 6 hours')

# Group by market/outcome
markets = defaultdict(list)
for t in trades:
    key = (t.get('conditionId', ''), t.get('outcomeIndex', 0))
    markets[key].append(t)

print(f'\nAnalyzing {len(markets)} unique market/outcomes...')

# Analyze each market
resolved_wins = []
resolved_losses = []
open_positions = []

for (cond_id, outcome_idx), market_trades in markets.items():
    if not market_trades:
        continue
    
    title = market_trades[0].get('title', 'Unknown')
    asset = market_trades[0].get('asset', '')
    outcome_name = market_trades[0].get('outcome', f'outcome_{outcome_idx}')
    
    # Calculate average entry price from target's BUY trades
    buy_trades = [t for t in market_trades if t.get('side') == 'BUY']
    sell_trades = [t for t in market_trades if t.get('side') == 'SELL']
    
    if not buy_trades:
        continue
        
    entry_prices = [float(t.get('price', 0)) for t in buy_trades]
    avg_entry = sum(entry_prices) / len(entry_prices)
    total_buy_size = sum(float(t.get('usdcSize', 0)) for t in buy_trades)
    total_sell_size = sum(float(t.get('usdcSize', 0)) for t in sell_trades)
    net_size = total_buy_size - total_sell_size
    
    # Get current market price
    try:
        book_url = f'https://clob.polymarket.com/book?token_id={asset}'
        book_resp = requests.get(book_url, timeout=10)
        book = book_resp.json()
        
        current_price = None
        if book.get('bids'):
            current_price = float(book['bids'][0]['price'])
        elif book.get('asks'):
            current_price = float(book['asks'][0]['price'])
    except:
        current_price = None
    
    # Determine if market is resolved (price at 0.01 or 0.99 typically means resolved)
    is_resolved = current_price is not None and (current_price <= 0.02 or current_price >= 0.98)
    
    trade_info = {
        'title': title[:50],
        'outcome': outcome_name,
        'entry': avg_entry,
        'current': current_price,
        'buy_size': total_buy_size,
        'net_size': net_size,
        'num_buys': len(buy_trades),
        'num_sells': len(sell_trades),
        'is_resolved': is_resolved,
    }
    
    if is_resolved:
        # Check if resolved in our favor (bought at low price, resolved to 1.0)
        # or against us (bought at high price, resolved to 0.0)
        if current_price >= 0.98:
            # Resolved YES - we won if we bought this outcome
            trade_info['result'] = 'WIN'
            trade_info['pnl'] = net_size * (1.0 - avg_entry) / avg_entry * 100
            resolved_wins.append(trade_info)
        else:
            # Resolved NO - we lost
            trade_info['result'] = 'LOSS'
            trade_info['pnl'] = -100  # Total loss
            resolved_losses.append(trade_info)
    else:
        # Market still open
        if current_price:
            trade_info['unrealized_pnl'] = (current_price - avg_entry) / avg_entry * 100
        else:
            trade_info['unrealized_pnl'] = 0
        open_positions.append(trade_info)

print(f'\n{"="*60}')
print(f'=== TARGET TRADER PERFORMANCE (Last 6 Hours) ===')
print(f'{"="*60}')
print(f'Resolved Wins: {len(resolved_wins)}')
print(f'Resolved Losses: {len(resolved_losses)}')
print(f'Open Positions: {len(open_positions)}')

if resolved_wins or resolved_losses:
    win_rate = len(resolved_wins) / (len(resolved_wins) + len(resolved_losses)) * 100
    print(f'Resolution Win Rate: {win_rate:.1f}%')

print(f'\n=== RESOLVED WINS ===')
for t in resolved_wins:
    print(f"  {t['title'][:40]}")
    print(f"    {t['outcome']} @ {t['entry']:.1%} -> RESOLVED YES | Size: ${t['buy_size']:.2f}")

print(f'\n=== RESOLVED LOSSES ===')
for t in resolved_losses:
    print(f"  {t['title'][:40]}")
    print(f"    {t['outcome']} @ {t['entry']:.1%} -> RESOLVED NO | Size: ${t['buy_size']:.2f}")

print(f'\n=== OPEN POSITIONS ===')
for t in sorted(open_positions, key=lambda x: -x.get('unrealized_pnl', 0)):
    current = t['current'] if t['current'] else 0
    print(f"  {t['title'][:40]}")
    print(f"    {t['outcome']} @ {t['entry']:.1%} -> Now {current:.1%} | Unrealized: {t.get('unrealized_pnl', 0):+.1f}% | Size: ${t['buy_size']:.2f}")

# Calculate total P&L
total_win_size = sum(t['buy_size'] for t in resolved_wins)
total_loss_size = sum(t['buy_size'] for t in resolved_losses)

print(f'\n{"="*60}')
print(f'=== P&L SUMMARY ===')
print(f'{"="*60}')
print(f'Won ${total_win_size:.2f} on {len(resolved_wins)} winning trades')
print(f'Lost ${total_loss_size:.2f} on {len(resolved_losses)} losing trades')
print(f'Net realized: ${total_win_size - total_loss_size:.2f}')

# Analyze by entry price to see filter impact
print(f'\n{"="*60}')
print(f'=== ENTRY PRICE ANALYSIS (for filter tuning) ===')
print(f'{"="*60}')

all_resolved = resolved_wins + resolved_losses
if all_resolved:
    high_entry = [t for t in all_resolved if t['entry'] > 0.70]
    mid_entry = [t for t in all_resolved if 0.30 <= t['entry'] <= 0.70]
    low_entry = [t for t in all_resolved if t['entry'] < 0.30]
    
    for label, group in [('High (>70%)', high_entry), ('Mid (30-70%)', mid_entry), ('Low (<30%)', low_entry)]:
        wins = len([t for t in group if t['result'] == 'WIN'])
        losses = len([t for t in group if t['result'] == 'LOSS'])
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        total_vol = sum(t['buy_size'] for t in group)
        print(f'{label}: {wins}W/{losses}L ({win_rate:.0f}% WR) - ${total_vol:.2f} volume')
