"""Analyze 24-hour performance of target trader."""

import requests
from datetime import datetime, timedelta
from collections import defaultdict

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'

# Get more trades - last 24 hours
url = f'https://data-api.polymarket.com/activity?user={TARGET}&limit=2000'
print('Fetching target trades (last 2000)...')
resp = requests.get(url, timeout=60)
all_trades = resp.json()
print(f'Fetched {len(all_trades)} activities')

cutoff_24h = datetime.now() - timedelta(hours=24)

# Filter to trades only
trades = []
for t in all_trades:
    if t.get('type', '').upper() != 'TRADE':
        continue
    ts_val = t.get('timestamp', 0)
    if isinstance(ts_val, int):
        ts = datetime.fromtimestamp(ts_val)
    else:
        continue
    if ts >= cutoff_24h:
        t['_datetime'] = ts
        trades.append(t)

print(f'Found {len(trades)} trades in last 24 hours')

# Group by market/outcome
markets = defaultdict(list)
for t in trades:
    key = (t.get('conditionId', ''), t.get('outcomeIndex', 0))
    markets[key].append(t)

# Analyze by hour buckets
hourly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'open': 0})

resolved_wins = 0
resolved_losses = 0
total_win_vol = 0
total_loss_vol = 0

for (cond_id, outcome_idx), market_trades in markets.items():
    if not market_trades:
        continue
    
    title = market_trades[0].get('title', 'Unknown')
    asset = market_trades[0].get('asset', '')
    
    buy_trades = [t for t in market_trades if t.get('side') == 'BUY']
    if not buy_trades:
        continue
    
    entry_prices = [float(t.get('price', 0)) for t in buy_trades]
    avg_entry = sum(entry_prices) / len(entry_prices)
    total_size = sum(float(t.get('usdcSize', 0)) for t in buy_trades)
    first_trade_time = min(t['_datetime'] for t in buy_trades)
    hour_bucket = first_trade_time.hour
    
    # Get current price
    try:
        book_url = f'https://clob.polymarket.com/book?token_id={asset}'
        book_resp = requests.get(book_url, timeout=5)
        book = book_resp.json()
        current_price = None
        if book.get('bids'):
            current_price = float(book['bids'][0]['price'])
        elif book.get('asks'):
            current_price = float(book['asks'][0]['price'])
    except:
        current_price = None
    
    if current_price is None:
        continue
        
    is_resolved = current_price <= 0.02 or current_price >= 0.98
    
    if is_resolved:
        if current_price >= 0.98:
            resolved_wins += 1
            total_win_vol += total_size
            hourly_stats[hour_bucket]['wins'] += 1
        else:
            resolved_losses += 1
            total_loss_vol += total_size
            hourly_stats[hour_bucket]['losses'] += 1
    else:
        hourly_stats[hour_bucket]['open'] += 1

total = resolved_wins + resolved_losses
win_rate = resolved_wins / total * 100 if total > 0 else 0

print(f'\n=== 24 HOUR SUMMARY ===')
print(f'Resolved Wins: {resolved_wins}')
print(f'Resolved Losses: {resolved_losses}')
print(f'Win Rate: {win_rate:.1f}%')
print(f'Total Won: ${total_win_vol:.2f}')
print(f'Total Lost: ${total_loss_vol:.2f}')
print(f'Net: ${total_win_vol - total_loss_vol:.2f}')

print(f'\n=== BY HOUR ===')
for hour in sorted(hourly_stats.keys()):
    stats = hourly_stats[hour]
    w, l = stats['wins'], stats['losses']
    wr = w / (w + l) * 100 if (w + l) > 0 else 0
    o = stats['open']
    print(f'{hour:02d}:00 - Wins: {w}, Losses: {l}, Open: {o} (WR: {wr:.0f}%)')
