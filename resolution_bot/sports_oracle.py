"""
Sports Resolution Oracle - MVP

RULES:
1. Find sports markets (Team A vs Team B)
2. Check if game_status == FINAL
3. Determine WINNER from game result
4. Return winner info for buying
"""
import re
import logging
import httpx
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SportsResult:
    """Result from checking a sports market"""
    market_id: str
    market_title: str
    game_final: bool
    winner: Optional[str]
    winner_token_id: Optional[str]
    winner_price: Optional[float]
    reasoning: str


class SportsOracle:
    """
    Oracle for sports markets.
    Uses ESPN API to check if games are final and determine winners.
    """
    
    ESPN_API = "https://site.api.espn.com/apis/site/v2/sports"
    
    SPORTS = {
        "nfl": "football/nfl",
        "nba": "basketball/nba", 
        "mlb": "baseball/mlb",
        "nhl": "hockey/nhl",
        "ncaaf": "football/college-football",
        "ncaab": "basketball/mens-college-basketball",
    }
    
    def is_sports_market(self, market: Dict[str, Any]) -> bool:
        """Check if this is a Team A vs Team B sports market"""
        title = market.get("question", market.get("title", "")).lower()
        
        has_vs = " vs " in title or " vs. " in title
        has_beat = " beat " in title or " defeat " in title
        
        sport_keywords = ["nfl", "nba", "mlb", "nhl", "ncaa", "football", 
                         "basketball", "baseball", "hockey", "playoffs", "super bowl"]
        has_sport = any(kw in title for kw in sport_keywords)
        
        return (has_vs or has_beat) and has_sport
    
    def extract_teams(self, title: str) -> tuple:
        """Extract team names from market title"""
        title_lower = title.lower()
        
        # Pattern: "Team A vs Team B" or "Will Team A beat Team B?"
        vs_pattern = r"(?:will\s+)?(?:the\s+)?(.+?)\s+(?:vs\.?|beat|defeat)\s+(?:the\s+)?(.+?)(?:\?|$|\s+in\s+)"
        match = re.search(vs_pattern, title_lower, re.IGNORECASE)
        
        if match:
            team_a = match.group(1).strip()
            team_b = match.group(2).strip()
            return team_a, team_b
        
        return None, None
    
    async def fetch_games(self, sport: str) -> List[Dict]:
        """Fetch recent games from ESPN"""
        if sport not in self.SPORTS:
            return []
        
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.ESPN_API}/{self.SPORTS[sport]}/scoreboard"
                resp = await client.get(url, timeout=10.0)
                
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("events", [])
        except Exception as e:
            logger.error(f"ESPN API error: {e}")
        
        return []
    
    async def find_game(self, team_a: str, team_b: str) -> Optional[Dict]:
        """Find a game matching the two teams"""
        for sport in self.SPORTS:
            games = await self.fetch_games(sport)
            
            for game in games:
                competitions = game.get("competitions", [])
                if not competitions:
                    continue
                
                comp = competitions[0]
                competitors = comp.get("competitors", [])
                
                if len(competitors) != 2:
                    continue
                
                # Get team names from ESPN
                espn_team_names = []
                for c in competitors:
                    team_info = c.get("team", {})
                    names = [
                        team_info.get("displayName", "").lower(),
                        team_info.get("shortDisplayName", "").lower(),
                        team_info.get("name", "").lower(),
                        team_info.get("abbreviation", "").lower(),
                    ]
                    espn_team_names.append(names)
                
                # Check if our teams match
                def team_matches(our_team, espn_names):
                    our = our_team.lower()
                    for name in espn_names:
                        if our in name or name in our:
                            return True
                    return False
                
                a_match = team_matches(team_a, espn_team_names[0]) or team_matches(team_a, espn_team_names[1])
                b_match = team_matches(team_b, espn_team_names[0]) or team_matches(team_b, espn_team_names[1])
                
                if a_match and b_match:
                    return {
                        "game": game,
                        "competition": comp,
                        "competitors": competitors,
                        "sport": sport
                    }
        
        return None
    
    def get_game_status(self, game_data: Dict) -> tuple:
        """Check if game is final and who won. Returns (is_final, winner_name)"""
        comp = game_data.get("competition", {})
        status = comp.get("status", {})
        
        status_type = status.get("type", {})
        is_final = status_type.get("completed", False)
        state = status_type.get("state", "").lower()
        
        if not is_final and state != "post":
            return False, None
        
        # Find winner
        competitors = game_data.get("competitors", [])
        winner = None
        
        for c in competitors:
            if c.get("winner", False):
                team = c.get("team", {})
                winner = team.get("displayName") or team.get("name")
                break
        
        # If no winner flag, compare scores
        if not winner and len(competitors) == 2:
            score_a = int(competitors[0].get("score", 0))
            score_b = int(competitors[1].get("score", 0))
            
            if score_a > score_b:
                winner = competitors[0].get("team", {}).get("displayName")
            elif score_b > score_a:
                winner = competitors[1].get("team", {}).get("displayName")
        
        return True, winner
    
    def match_winner_to_outcome(self, winner: str, outcomes: List[str]) -> Optional[int]:
        """Match ESPN winner to market outcome index"""
        winner_lower = winner.lower()
        
        for i, outcome in enumerate(outcomes):
            outcome_lower = outcome.lower()
            if winner_lower in outcome_lower or outcome_lower in winner_lower:
                return i
        
        return None
    
    async def check_market(self, market: Dict[str, Any]) -> Optional[SportsResult]:
        """
        Check if a sports market is resolved.
        
        Returns SportsResult if game_status == FINAL
        """
        title = market.get("question", market.get("title", ""))
        market_id = market.get("condition_id", market.get("conditionId", ""))
        
        if not self.is_sports_market(market):
            return None
        
        team_a, team_b = self.extract_teams(title)
        if not team_a or not team_b:
            return SportsResult(
                market_id=market_id,
                market_title=title,
                game_final=False,
                winner=None,
                winner_token_id=None,
                winner_price=None,
                reasoning="Could not extract teams"
            )
        
        game_data = await self.find_game(team_a, team_b)
        if not game_data:
            return SportsResult(
                market_id=market_id,
                market_title=title,
                game_final=False,
                winner=None,
                winner_token_id=None,
                winner_price=None,
                reasoning=f"Game not found: {team_a} vs {team_b}"
            )
        
        # KEY RULE: game_status == FINAL
        is_final, espn_winner = self.get_game_status(game_data)
        
        if not is_final:
            return SportsResult(
                market_id=market_id,
                market_title=title,
                game_final=False,
                winner=None,
                winner_token_id=None,
                winner_price=None,
                reasoning="Game NOT final"
            )
        
        if not espn_winner:
            return SportsResult(
                market_id=market_id,
                market_title=title,
                game_final=True,
                winner=None,
                winner_token_id=None,
                winner_price=None,
                reasoning="Game final but tie/no winner"
            )
        
        # Get market outcomes and prices
        outcomes = market.get("outcomes", [])
        prices = []
        if "outcomePrices" in market:
            price_data = market["outcomePrices"]
            if isinstance(price_data, str):
                price_data = price_data.strip("[]").split(",")
            prices = [float(p) for p in price_data]
        
        token_ids = []
        if "clobTokenIds" in market:
            tid_data = market["clobTokenIds"]
            if isinstance(tid_data, str):
                tid_data = tid_data.strip("[]").replace('"', '').split(",")
            token_ids = [t.strip() for t in tid_data]
        
        # Match ESPN winner to market outcome
        winner_idx = self.match_winner_to_outcome(espn_winner, outcomes)
        
        if winner_idx is None:
            return SportsResult(
                market_id=market_id,
                market_title=title,
                game_final=True,
                winner=None,
                winner_token_id=None,
                winner_price=None,
                reasoning=f"Can't match '{espn_winner}' to {outcomes}"
            )
        
        winner_outcome = outcomes[winner_idx]
        winner_price = prices[winner_idx] if winner_idx < len(prices) else None
        winner_token_id = token_ids[winner_idx] if winner_idx < len(token_ids) else None
        
        return SportsResult(
            market_id=market_id,
            market_title=title,
            game_final=True,
            winner=winner_outcome,
            winner_token_id=winner_token_id,
            winner_price=winner_price,
            reasoning=f"FINAL: {espn_winner} wins @ ${winner_price:.4f if winner_price else 0}"
        )
