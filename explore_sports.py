"""Explore Polymarket sports markets by category"""
import asyncio
import httpx

GAMMA_API = "https://gamma-api.polymarket.com"

async def main():
    async with httpx.AsyncClient() as client:
        # Get events filtered by sports category
        print("=== SPORTS EVENTS (active, not closed) ===")
        resp = await client.get(
            f"{GAMMA_API}/events",
            params={
                "active": "true",
                "closed": "false", 
                "limit": 100
            },
            timeout=10.0
        )
        
        if resp.status_code == 200:
            events = resp.json()
            
            # Filter by Sports category
            sports_events = [e for e in events if e.get("category") == "Sports"]
            print(f"Total events: {len(events)}")
            print(f"Sports events: {len(sports_events)}")
            print()
            
            for e in sports_events[:15]:
                title = e.get("title", "")
                print(f"Event: {title}")
                markets = e.get("markets", [])
                for m in markets[:2]:
                    q = m.get("question", m.get("title", ""))
                    outcomes = m.get("outcomes", "")
                    print(f"  Market: {q}")
                    print(f"  Outcomes: {outcomes}")
                print("-" * 50)

asyncio.run(main())
