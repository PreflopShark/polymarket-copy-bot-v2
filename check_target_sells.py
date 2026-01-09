import requests

# Check target trader's activity
url = 'https://data-api.polymarket.com/activity?user=0x63ce342161250d705dc0b16df89036c8e5f9ba9a&limit=500'
activity = requests.get(url).json()
trades = [a for a in activity if a.get('type') == 'TRADE']
buys = [t for t in trades if t.get('side') == 'BUY']
sells = [t for t in trades if t.get('side') == 'SELL']

print(f'Target trader trades: {len(trades)}')
print(f'BUYs: {len(buys)}')
print(f'SELLs: {len(sells)}')

if sells:
    print('\nSample SELL trades:')
    for s in sells[:10]:
        title = s.get('title', '?')[:40]
        size = s.get('size', 0)
        print(f'  {title} | SELL | shares={size}')

# Check OUR activity for sells
print('\n\n=== OUR ACCOUNT ===')
our_url = 'https://data-api.polymarket.com/activity?user=0x9c76847744942b41d3bBDcFE5A3B98AE67a95750&limit=500'
our_activity = requests.get(our_url).json()
our_trades = [a for a in our_activity if a.get('type') == 'TRADE']
our_buys = [t for t in our_trades if t.get('side') == 'BUY']
our_sells = [t for t in our_trades if t.get('side') == 'SELL']

print(f'Our trades: {len(our_trades)}')
print(f'BUYs: {len(our_buys)}')
print(f'SELLs: {len(our_sells)}')
