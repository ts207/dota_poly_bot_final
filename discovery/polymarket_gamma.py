# discovery/polymarket_gamma.py
"""Polymarket Gamma market discovery for Dota 2 markets.

Gamma is used only for read-only discovery/metadata. Trading/book data still
uses CLOB token IDs through the websocket/order APIs.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import aiohttp


GAMMA_BASE = "https://gamma-api.polymarket.com"


def _parse_json_array(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            # Some API mirrors return comma-separated strings; keep a safe fallback.
            return [x.strip().strip('"') for x in value.split(",") if x.strip()]
    return []


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _tokens(s: Any) -> set[str]:
    return {x for x in _norm(s).split() if x}



BAD_MARKET_TERMS = {
    "tournament", "outright", "champion", "winner of",
    "first blood", "total kills", "handicap", "spread",
    "series score", "correct score", "most kills", "roshan", "duration", "over", "under"
}


def parse_game_number(text: str) -> Optional[int]:
    """Extract game number from market text (e.g. 'Game 2 Winner' -> 2)."""
    match = re.search(r"(?:game|map)\s*(\d+)", text.lower())
    if match:
        return int(match.group(1))
    return None


def _is_probably_match_winner_market(market: "DiscoveredMarket") -> bool:
    """Keep only simple binary match-winner style markets by default."""
    if len(market.outcomes) != 2 or len(market.clob_token_ids) != 2:
        return False
    text = _norm(" ".join([market.question, market.slug, " ".join(market.outcomes)]))
    # Reject obvious derivatives/props.
    if any(term in text for term in BAD_MARKET_TERMS):
        return False
    # Must look like a versus/winner market, not just any Dota-related question.
    raw = " ".join([market.question.lower(), market.slug.lower()])
    if not any(x in raw for x in (" vs ", " v ", " beat", " win", "winner")):
        return False
    return True


def _team_score(team: str, text: str) -> float:
    """Fuzzy score for team-name matching without external dependencies."""
    team_n = _norm(team)
    text_n = _norm(text)
    if not team_n or not text_n:
        return 0.0
    if team_n in text_n:
        return 1.0
    team_tokens = _tokens(team_n)
    text_tokens = _tokens(text_n)
    if not team_tokens:
        return 0.0
    overlap = len(team_tokens & text_tokens) / max(len(team_tokens), 1)
    return overlap


@dataclass
class DiscoveredMarket:
    gamma_id: str
    condition_id: str
    question: str
    slug: str
    outcomes: List[str]
    clob_token_ids: List[str]
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    spread: Optional[float] = None
    liquidity: Optional[float] = None
    volume24hr: Optional[float] = None
    end_date: Optional[str] = None

    @property
    def url(self) -> str:
        return f"https://polymarket.com/market/{self.slug}" if self.slug else ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gamma_id": self.gamma_id,
            "condition_id": self.condition_id,
            "question": self.question,
            "slug": self.slug,
            "outcomes": self.outcomes,
            "clob_token_ids": self.clob_token_ids,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread,
            "liquidity": self.liquidity,
            "volume24hr": self.volume24hr,
            "end_date": self.end_date,
            "url": self.url,
        }


class PolymarketGammaDiscovery:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None, timeout_s: float = 8.0):
        self._external_session = session
        self._session: Optional[aiohttp.ClientSession] = session
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)

    async def close(self):
        if not self._external_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def _get_json(self, path: str, params: Dict[str, Any]) -> Any:
        session = await self._get_session()
        async with session.get(f"{GAMMA_BASE}{path}", params=params) as r:
            r.raise_for_status()
            return await r.json()

    @staticmethod
    def _market_from_raw(raw: Dict[str, Any]) -> Optional[DiscoveredMarket]:
        outcomes = [str(x) for x in _parse_json_array(raw.get("outcomes"))]
        token_ids = [str(x) for x in _parse_json_array(raw.get("clobTokenIds"))]
        if len(outcomes) < 2 or len(token_ids) < 2:
            return None
        if len(outcomes) != len(token_ids):
            # Keep only aligned pairs; Gamma should usually return equal lengths.
            n = min(len(outcomes), len(token_ids))
            outcomes, token_ids = outcomes[:n], token_ids[:n]
        return DiscoveredMarket(
            gamma_id=str(raw.get("id") or ""),
            condition_id=str(raw.get("conditionId") or raw.get("condition_id") or ""),
            question=str(raw.get("question") or raw.get("title") or ""),
            slug=str(raw.get("slug") or ""),
            outcomes=outcomes,
            clob_token_ids=token_ids,
            best_bid=_to_float(raw.get("bestBid")),
            best_ask=_to_float(raw.get("bestAsk")),
            spread=_to_float(raw.get("spread")),
            liquidity=_to_float(raw.get("liquidityNum") or raw.get("liquidity")),
            volume24hr=_to_float(raw.get("volume24hr") or raw.get("volume24hrNum")),
            end_date=str(raw.get("endDate") or raw.get("endDateIso") or ""),
        )

    async def search_dota_markets(
        self,
        query_terms: Sequence[str] = ("dota", "dota 2", "dota2"),
        limit_per_query: int = 50,
        active: bool = True,
        closed: bool = False,
        strict_match_winner_only: bool = True,
    ) -> List[DiscoveredMarket]:
        """Search Gamma for active Dota/Dota2 markets and return unique markets.
        
        Uses the /public-search endpoint which supports full-text search across events.
        """
        seen: set[str] = set()
        markets: List[DiscoveredMarket] = []
        for q in query_terms:
            params = {
                "q": q,
                "active": str(active).lower(),
            }
            try:
                data = await self._get_json("/public-search", params)
            except Exception:
                continue
            
            # /public-search returns {"events": [...], "tags": [...], "profiles": [...]}
            events = data.get("events") if isinstance(data, dict) else []
            if not events:
                continue
                
            for event in events:
                raw_markets = event.get("markets") or []
                for raw in raw_markets:
                    if not isinstance(raw, dict):
                        continue
                    m = self._market_from_raw(raw)
                    if not m:
                        continue
                    # Require Dota-ish text somewhere; q search can be broad.
                    hay = _norm(" ".join([
                        m.question, 
                        m.slug, 
                        " ".join(m.outcomes), 
                        str(raw.get("description", "")),
                        str(event.get("title", ""))
                    ]))
                    if not any(term in hay for term in ("dota", "dota2", "dota 2")):
                        continue
                    if strict_match_winner_only and not _is_probably_match_winner_market(m):
                        continue
                    key = m.condition_id or m.gamma_id or m.slug
                    if key in seen:
                        continue
                    seen.add(key)
                    markets.append(m)
        markets.sort(key=lambda m: (m.volume24hr or 0.0, m.liquidity or 0.0), reverse=True)
        return markets

    @staticmethod
    def choose_market(
        markets: Sequence[DiscoveredMarket],
        radiant_team: str = "",
        dire_team: str = "",
        target_match: str = "",
        min_score: float = 0.35,
        target_game_number: Optional[int] = None,
    ) -> Optional[Tuple[DiscoveredMarket, Dict[str, str]]]:
        """Pick the best market and map team sides to CLOB token IDs.

        Returns (market, mapping) where mapping includes RADIANT_TOKEN_ID and
        DIRE_TOKEN_ID if both can be inferred. It does not assume outcome order;
        it scores each outcome against the requested team names.
        """
        if not markets:
            return None

        radiant_team = radiant_team or ""
        dire_team = dire_team or ""
        target_match = target_match or ""

        best: Optional[Tuple[float, DiscoveredMarket, Dict[str, str]]] = None
        for m in markets:
            text = " ".join([m.question, m.slug, " ".join(m.outcomes)])
            base = 0.0

            m_game = parse_game_number(m.question + " " + m.slug)
            if target_game_number is not None:
                if m_game == target_game_number:
                    base += 1.0
                elif m_game is not None:
                    continue

            if target_match:
                base += _team_score(target_match, text)
            if radiant_team:
                base += _team_score(radiant_team, text)
            if dire_team:
                base += _team_score(dire_team, text)

            r_idx = _best_outcome_index(m.outcomes, radiant_team) if radiant_team else None
            d_idx = _best_outcome_index(m.outcomes, dire_team) if dire_team else None
            if r_idx is None and target_match:
                r_idx = _best_outcome_index(m.outcomes, target_match)

            # For binary team markets, if one side is known, infer the other side.
            if d_idx is None and r_idx is not None and len(m.outcomes) == 2:
                d_idx = 1 - r_idx
            if r_idx is None and d_idx is not None and len(m.outcomes) == 2:
                r_idx = 1 - d_idx

            if r_idx is None or d_idx is None or r_idx == d_idx:
                score = base
                mapping: Dict[str, str] = {}
            else:
                r_score = _team_score(radiant_team or target_match, m.outcomes[r_idx]) if (radiant_team or target_match) else 0.2
                d_score = _team_score(dire_team, m.outcomes[d_idx]) if dire_team else 0.2
                if radiant_team and r_score < 0.5:
                    continue
                if dire_team and d_score < 0.5:
                    continue
                score = base + r_score + d_score
                mapping = {
                    "MARKET_ID": m.condition_id or m.gamma_id,
                    "GAMMA_MARKET_ID": m.gamma_id,
                    "POLYMARKET_SLUG": m.slug,
                    "RADIANT_TOKEN_ID": m.clob_token_ids[r_idx],
                    "DIRE_TOKEN_ID": m.clob_token_ids[d_idx],
                    "RADIANT_OUTCOME": m.outcomes[r_idx],
                    "DIRE_OUTCOME": m.outcomes[d_idx],
                }

            # Liquidity tie-breaker.
            score += min((m.liquidity or 0.0) / 250000.0, 0.10)
            score += min((m.volume24hr or 0.0) / 250000.0, 0.10)
            if best is None or score > best[0]:
                best = (score, m, mapping)

        if best is None or best[0] < min_score or not best[2].get("RADIANT_TOKEN_ID"):
            return None
        return best[1], best[2]


def map_market_to_team_tokens(market: DiscoveredMarket, radiant_team: str, dire_team: str) -> Optional[Dict[str, str]]:
    """Map a discovered binary market's outcomes to current Dota Radiant/Dire teams."""
    r_idx = _best_outcome_index(market.outcomes, radiant_team)
    d_idx = _best_outcome_index(market.outcomes, dire_team)
    if r_idx is None or d_idx is None or r_idx == d_idx:
        return None
    if _team_score(radiant_team, market.outcomes[r_idx]) < 0.5 or _team_score(dire_team, market.outcomes[d_idx]) < 0.5:
        return None
    return {
        "MARKET_ID": market.condition_id or market.gamma_id,
        "GAMMA_MARKET_ID": market.gamma_id,
        "POLYMARKET_SLUG": market.slug,
        "RADIANT_TOKEN_ID": market.clob_token_ids[r_idx],
        "DIRE_TOKEN_ID": market.clob_token_ids[d_idx],
        "RADIANT_OUTCOME": market.outcomes[r_idx],
        "DIRE_OUTCOME": market.outcomes[d_idx],
    }


def market_team_pair_hint(market: DiscoveredMarket) -> Tuple[str, str]:
    """Best-effort pair of team names from binary outcomes."""
    if len(market.outcomes) >= 2:
        return str(market.outcomes[0]), str(market.outcomes[1])
    return "", ""


async def discover_polymarket_dota_target(
    radiant_team: str = "",
    dire_team: str = "",
    target_match: str = "",
    query_terms: Sequence[str] = ("dota", "dota 2", "dota2"),
) -> Optional[Tuple[DiscoveredMarket, Dict[str, str], List[DiscoveredMarket]]]:
    disc = PolymarketGammaDiscovery()
    try:
        markets = await disc.search_dota_markets(query_terms=query_terms)
        chosen = disc.choose_market(markets, radiant_team=radiant_team, dire_team=dire_team, target_match=target_match)
        if not chosen:
            return None
        market, mapping = chosen
        return market, mapping, list(markets)
    finally:
        await disc.close()


def _best_outcome_index(outcomes: Sequence[str], team: str) -> Optional[int]:
    if not team or not outcomes:
        return None
    scores = [(_team_score(team, outcome), i) for i, outcome in enumerate(outcomes)]
    scores.sort(reverse=True)
    if not scores or scores[0][0] <= 0:
        return None
    return scores[0][1]


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None
