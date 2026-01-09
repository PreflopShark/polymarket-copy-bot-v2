"""Check recent target trades."""
import requests
from datetime import datetime

TARGET = '0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
url = f'https://data-api.polymarket.com/activity?user={TARGET}&limit=20'
resp = requests.get(url, timeout=30)
trades = resp.json()

print('Most recent 20 activities:')
for i, t in enumerate(trades[:20]):
    ts = datetime.fromtimestamp(t.get('timestamp', 0))
    side = t.get('side', '?')
    title = t.get('title', 'Unknown')[:40]
    price = t.get('price', 0)
    size = t.get('usdcSize', 0)
    ttype = t.get('type', '?')
    outcome = t.get('outcome', '?')
    time_str = ts.strftime('%H:%M')
    print(f'{i+1}. [{time_str}] {ttype} {side} {outcome} @ {price:.2%} ${size:.2f} - {title}')
