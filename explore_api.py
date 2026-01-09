"""Explore Polymarket API structure for sports"""
import asyncio
import httpx

GAMMA_API = "https://gamma-api.polymarket.com"

async def main():
    async with httpx.AsyncClient() as client:
        # Try events endpoint
        print("=== EVENTS ===")
        resp = await client.get(f"{GAMMA_API}/events", params={"limit": 50}, timeout=10.0)
        if resp.status_code == 200:
            events = resp.json()
            print(f"Events returned: {len(events)}")
            # Look at structure
            if events:
                e = events[0]
                print(f"Event keys: {e.keys()}")
                print(f"Sample event: {e.get('title', e.get('slug'))}")
                # Look for tags/category
                for k in ["tags", "category", "tag", "type", "group"]:
                    if k in e:
                        print(f"{k}: {e[k]}")
        
        # Try searching for sports
        print("\n=== SEARCH 'NFL' ===")
        resp = await client.get(f"{GAMMA_API}/events", params={"text": "NFL", "limit": 20}, timeout=10.0)
        if resp.status_code == 200:
            events = resp.json()
            print(f"Found: {len(events)}")
            for e in events[:5]:
                print(f" - {e.get('title', e.get('slug'))}")
        
        print("\n=== SEARCH 'vs' ===")
        resp = await client.get(f"{GAMMA_API}/events", params={"text": "vs", "limit": 20}, timeout=10.0)
        if resp.status_code == 200:
            events = resp.json()
            print(f"Found: {len(events)}")
            for e in events[:5]:
                print(f" - {e.get('title', e.get('slug'))}")
        
        # Check specific NFL event that might exist
        print("\n=== SEARCH 'Super Bowl' ===")
        resp = await client.get(f"{GAMMA_API}/events", params={"text": "Super Bowl", "limit": 20}, timeout=10.0)
        if resp.status_code == 200:
            events = resp.json()
            print(f"Found: {len(events)}")
            for e in events[:5]:
                print(f" - {e.get('title', e.get('slug'))}")
                # Print markets in event
                for m in e.get("markets", [])[:3]:
                    print(f"    Market: {m.get('question', m.get('title', ''))}")
        
        # Look for basketball
        print("\n=== SEARCH 'NBA' ===")
        resp = await client.get(f"{GAMMA_API}/events", params={"text": "NBA", "limit": 20}, timeout=10.0)
        if resp.status_code == 200:
            events = resp.json()
            print(f"Found: {len(events)}")
            for e in events[:5]:
                print(f" - {e.get('title', e.get('slug'))}")

asyncio.run(main())
