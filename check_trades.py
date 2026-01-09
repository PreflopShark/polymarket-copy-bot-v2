"""Quick script to check recent trades."""
import requests
import os
from dotenv import load_dotenv

load_dotenv()

address = os.getenv("FUNDER_ADDRESS")
print(f"Checking trades for: {address}\n")

r = requests.get(f"https://data-api.polymarket.com/activity?user={address}&limit=10")
data = r.json()

print(f"{'Type':<10} | {'Side':<4} | {'Amount':>10} | Market")
print("-" * 80)

for t in data:
    trade_type = t.get('type', '?')
    side = t.get('side', '')
    amount = float(t.get('usdcSize', 0))
    title = t.get('title', '')[:45]
    print(f"{trade_type:<10} | {side:<4} | ${amount:>8.2f} | {title}")
