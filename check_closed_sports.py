"""Look at closed sports events"""
import httpx

GAMMA_API = "https://gamma-api.polymarket.com"

resp = httpx.get(f"{GAMMA_API}/events", params={"limit": 200}, timeout=10.0)
events = resp.json()

# Find closed sports
sports_events = [e for e in events if e.get("category") == "Sports"]
closed_sports = [e for e in sports_events if e.get("closed")]

print(f"Closed sports events: {len(closed_sports)}")
print()

for e in closed_sports[:5]:
    title = e.get("title", "")
    print(f"Event: {title}")
    markets = e.get("markets", [])
    for m in markets[:1]:
        q = m.get("question", m.get("title", ""))
        outcomes = m.get("outcomes", "")
        print(f"  Market: {q}")
        print(f"  Outcomes: {outcomes}")
    print("-" * 50)

print("\n\n=== Looking at a specific sports market ===")
# Get a specific NFL market if available
for e in sports_events:
    title = e.get("title", "").lower()
    if "nfl" in title or "nba" in title:
        print(f"\nEvent: {e.get('title')}")
        print(f"Active: {e.get('active')}, Closed: {e.get('closed')}")
        for m in e.get("markets", [])[:2]:
            print(f"  Q: {m.get('question')}")
            print(f"  Outcomes: {m.get('outcomes')}")
            print(f"  TokenIDs: {[t.get('token_id') for t in m.get('tokens', [])]}")
        break
