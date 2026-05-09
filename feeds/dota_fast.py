# feeds/dota_fast.py
import time
import aiohttp
from typing import Optional, Dict, Any, Iterable, List


class DotaFastFeed:
    """
    Fast Dota feed using GetTopLiveGame.

    GetTopLiveGame exposes radiant_lead, not real total team net worth. This
    feed keeps nw_diff as raw radiant_lead and intentionally does not invent
    total net worth or percentage lead.
    """

    def __init__(
        self,
        key: str,
        target_match_name: str = "",
        target_radiant_team: str = "",
        target_dire_team: str = "",
        target_server_steam_id: str = "",
        poll_interval: float = 2.0,
        partners: Iterable[int] = (0, 1, 2, 3),
    ):
        self.key = key
        self.target_match_name = target_match_name.lower().strip()
        self.target_radiant_team = target_radiant_team.lower().strip()
        self.target_dire_team = target_dire_team.lower().strip()
        self.target_server_steam_id = str(target_server_steam_id or "").strip()
        self.poll_interval = poll_interval
        self.partners: List[int] = list(partners)
        self.url = "https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/"
        self.latest: Optional[Dict[str, Any]] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_found_print_s: float = 0.0

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    @staticmethod
    def _norm_team(game: Dict[str, Any], key: str) -> str:
        return str(game.get(key, "") or "").lower().strip()

    @staticmethod
    def _name_match(configured: str, actual: str) -> bool:
        configured = " ".join(str(configured or "").lower().replace(".", " ").split())
        actual = " ".join(str(actual or "").lower().replace(".", " ").split())
        if not configured or not actual:
            return False
        if configured == actual:
            return True
        # Allow longer configured names to match aliases, but avoid dangerous 1-2 char substring matches.
        if len(configured) >= 4 and configured in actual:
            return True
        c_tokens = set(configured.split())
        a_tokens = set(actual.split())
        return bool(c_tokens) and len(c_tokens & a_tokens) / max(len(c_tokens), 1) >= 0.75

    def _matches_target(self, game: Dict[str, Any]) -> bool:
        server_id = str(game.get("server_steam_id") or "").strip()
        if self.target_server_steam_id:
            return server_id == self.target_server_steam_id

        radiant = self._norm_team(game, "team_name_radiant")
        dire = self._norm_team(game, "team_name_dire")

        if self.target_radiant_team and self.target_dire_team:
            return self._name_match(self.target_radiant_team, radiant) and self._name_match(self.target_dire_team, dire)

        # Backward-compatible fallback. Safer exact pair/server matching is preferred.
        if self.target_match_name:
            return self.target_match_name in radiant or self.target_match_name in dire

        # No configured target: never silently accept the first live game.
        return False

    async def _fetch_partner(self, session: aiohttp.ClientSession, partner: int) -> Optional[Dict[str, Any]]:
        params = {"key": self.key, "partner": partner}
        async with session.get(self.url, params=params) as r:
            if r.status != 200:
                return None
            data = await r.json()

        for game in data.get("game_list", []):
            if self._matches_target(game):
                game["_partner"] = partner
                return game
        return None

    async def fetch_live_games(self) -> List[Dict[str, Any]]:
        """Return all live games visible through configured partners."""
        session = await self._get_session()
        games: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for partner in self.partners:
            params = {"key": self.key, "partner": partner}
            try:
                async with session.get(self.url, params=params) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()
            except Exception:
                continue
            for game in data.get("game_list", []):
                key = str(game.get("server_steam_id") or game.get("lobby_id") or id(game))
                if key in seen:
                    continue
                seen.add(key)
                game["_partner"] = partner
                games.append(game)
        return games

    @staticmethod
    def team_pair_matches(game: Dict[str, Any], team_a: str, team_b: str) -> bool:
        radiant = DotaFastFeed._norm_team(game, "team_name_radiant")
        dire = DotaFastFeed._norm_team(game, "team_name_dire")
        a = str(team_a or "").lower().strip()
        b = str(team_b or "").lower().strip()
        return bool(a and b and (
            (DotaFastFeed._name_match(a, radiant) and DotaFastFeed._name_match(b, dire))
            or (DotaFastFeed._name_match(a, dire) and DotaFastFeed._name_match(b, radiant))
        ))

    async def find_live_game_by_team_pair(self, team_a: str, team_b: str) -> Optional[Dict[str, Any]]:
        for game in await self.fetch_live_games():
            if self.team_pair_matches(game, team_a, team_b):
                return game
        return None

    def set_target_server(self, server_steam_id: str):
        self.target_server_steam_id = str(server_steam_id or "").strip()

    async def fetch_once(self) -> Optional[Dict[str, Any]]:
        try:
            session = await self._get_session()
            target_game = None
            for partner in self.partners:
                target_game = await self._fetch_partner(session, partner)
                if target_game:
                    break

            if not target_game:
                return None

            radiant_name = target_game.get("team_name_radiant", "Radiant")
            dire_name = target_game.get("team_name_dire", "Dire")
            now_s = time.time()
            if now_s - self._last_found_print_s >= 20:
                print(
                    f"Dota Feed: Found {radiant_name} vs {dire_name} "
                    f"via partner={target_game.get('_partner')}"
                )
                self._last_found_print_s = now_s

            lead = float(target_game.get("radiant_lead", 0) or 0)

            tick = {
                "ts_ms": int(time.time() * 1000),
                "match_key": str(target_game.get("server_steam_id") or target_game.get("lobby_id") or ""),
                "server_steam_id": str(target_game.get("server_steam_id") or ""),
                "partner": int(target_game.get("_partner", -1)),
                "radiant_team": radiant_name,
                "dire_team": dire_name,
                "game_time": float(target_game.get("game_time", 0) or 0),
                "radiant_score": int(target_game.get("radiant_score", 0) or 0),
                "dire_score": int(target_game.get("dire_score", 0) or 0),
                # Compatibility fields. Do not interpret as true team net worth.
                "radiant_nw": lead if lead > 0 else 0.0,
                "dire_nw": abs(lead) if lead < 0 else 0.0,
                "nw_diff": lead,
                "total_nw": 0.0,
                "nw_diff_pct": 0.0,
                "building_state": int(target_game.get("building_state", 0) or 0),
            }

            self.latest = tick
            return tick
        except Exception as e:
            print(f"Error fetching Dota data: {e}")
            return None
