"""Compare our bot's execution vs what target did."""

import requests
from datetime import datetime, timedelta
from collections import defaultdict
import json
import os

# Load our session data
session_files = sorted([f for f in os.listdir('.') if f.startswith('session_') and f.endswith('.json')])
latest_session = session_files[-1] if session_files else None

print(f'Latest session file: {latest_session}')

if latest_session:
    with open(latest_session) as f:
        session = json.load(f)
    print(f"Session stats: {session.get('stats', {})}")

# Get OUR positions
MY_PROXY = '0x9c76847744942b41d3bbdcfe5a3b98ae67a95750'
url = f'https://data-api.polymarket.com/positions?user={MY_PROXY}'
print(f'\nFetching our positions...')
resp = requests.get(url, timeout=30)
our_positions = resp.json()
print(f'We have {len(our_positions)} positions')

# Calculate P&L
total_cost = 0
total_value = 0

print('\n=== OUR CURRENT POSITIONS ===')
for p in our_positions:
    title = p.get('title', 'Unknown')[:50]
    outcome = p.get('outcome', '?')
    size = float(p.get('size', 0) or 0)
    avg_price = float(p.get('avgPrice', 0) or 0)
    cur_price = float(p.get('curPrice', 0) or 0)
    value = float(p.get('currentValue', 0) or 0)
    cost = size * avg_price
    
    pnl = value - cost
    pnl_pct = (pnl / cost * 100) if cost > 0 else 0
    
    total_cost += cost
    total_value += value
    
    if size > 0:
        print(f'{title}')
        print(f'  {outcome}: {size:.1f} shares @ {avg_price:.2%} -> now {cur_price:.2%}')
        print(f'  Cost: ${cost:.2f} | Value: ${value:.2f} | P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)')
        print()

print(f'\n=== PORTFOLIO SUMMARY ===')
print(f'Total Cost Basis: ${total_cost:.2f}')
print(f'Current Value: ${total_value:.2f}')
print(f'Unrealized P&L: ${total_value - total_cost:.2f} ({((total_value/total_cost)-1)*100 if total_cost > 0 else 0:+.1f}%)')

# Get our recent trades
url = f'https://data-api.polymarket.com/activity?user={MY_PROXY}&limit=100'
print(f'\nFetching our recent trades...')
resp = requests.get(url, timeout=30)
our_trades = resp.json()
our_trades = [t for t in our_trades if t.get('type', '').upper() == 'TRADE']

print(f'Our recent trades: {len(our_trades)}')

# Group by market
our_markets = defaultdict(list)
for t in our_trades:
    key = (t.get('conditionId', ''), t.get('outcomeIndex', 0))
    our_markets[key].append(t)

print(f'\n=== OUR TRADE ANALYSIS ===')
print(f'Traded in {len(our_markets)} unique market/outcomes')

# Calculate win/loss on resolved positions
wins = 0
losses = 0
win_value = 0
loss_value = 0

for (cond_id, outcome_idx), trades in our_markets.items():
    buy_trades = [t for t in trades if t.get('side') == 'BUY']
    if not buy_trades:
        continue
    
    title = buy_trades[0].get('title', 'Unknown')[:40]
    asset = buy_trades[0].get('asset', '')
    outcome = buy_trades[0].get('outcome', '?')
    
    total_bought = sum(float(t.get('usdcSize', 0)) for t in buy_trades)
    avg_price = sum(float(t.get('price', 0)) for t in buy_trades) / len(buy_trades)
    
    # Get current price
    try:
        book_url = f'https://clob.polymarket.com/book?token_id={asset}'
        book_resp = requests.get(book_url, timeout=5)
        book = book_resp.json()
        cur_price = None
        if book.get('bids'):
            cur_price = float(book['bids'][0]['price'])
        elif book.get('asks'):
            cur_price = float(book['asks'][0]['price'])
    except:
        cur_price = None
    
    if cur_price is None:
        continue
    
    is_resolved = cur_price <= 0.02 or cur_price >= 0.98
    
    if is_resolved:
        if cur_price >= 0.98:
            wins += 1
            win_value += total_bought
            print(f'WIN: {title} | {outcome} @ {avg_price:.1%} -> RESOLVED YES | ${total_bought:.2f}')
        else:
            losses += 1
            loss_value += total_bought
            print(f'LOSS: {title} | {outcome} @ {avg_price:.1%} -> RESOLVED NO | ${total_bought:.2f}')

print(f'\n=== OUR RESOLUTION SUMMARY ===')
print(f'Wins: {wins} (${win_value:.2f})')
print(f'Losses: {losses} (${loss_value:.2f})')
if wins + losses > 0:
    print(f'Win Rate: {wins/(wins+losses)*100:.1f}%')
    print(f'Net P&L on resolved: ${win_value - loss_value:.2f}')
