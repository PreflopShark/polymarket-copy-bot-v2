"""Explore Polymarket sports markets"""
import httpx

GAMMA_API = "https://gamma-api.polymarket.com"

# Get ALL events (not filtered)
resp = httpx.get(f"{GAMMA_API}/events", params={"limit": 200}, timeout=10.0)
events = resp.json()

# Filter by Sports category client-side
sports_events = [e for e in events if e.get("category") == "Sports"]
print(f"Total events: {len(events)}")
print(f"Sports events: {len(sports_events)}")

# Find active ones
active_sports = [e for e in sports_events if e.get("active") and not e.get("closed")]
print(f"Active sports events: {len(active_sports)}")
print()

for e in active_sports[:10]:
    title = e.get("title", "")
    print(f"\nEvent: {title}")
    print(f"Active: {e.get('active')}, Closed: {e.get('closed')}")
    markets = e.get("markets", [])
    for m in markets[:2]:
        q = m.get("question", m.get("title", ""))
        outcomes = m.get("outcomes", "")
        active = m.get("active", False)
        closed = m.get("closed", False)
        print(f"  Market: {q}")
        print(f"  Outcomes: {outcomes}")
        print(f"  Active: {active}, Closed: {closed}")
    print("-" * 50)
