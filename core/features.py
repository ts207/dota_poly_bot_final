# core/features.py
from collections import deque
from typing import Dict, Any, Optional


class RollingWindow:
    def __init__(self, max_seconds: int = 300):
        self.max_ms = max_seconds * 1000
        self.items = deque()

    def add(self, tick: Dict[str, Any]):
        self.items.append(tick)
        cutoff = tick["ts_ms"] - self.max_ms
        while self.items and self.items[0]["ts_ms"] < cutoff:
            self.items.popleft()

    def closest_ago(self, now_ms: int, seconds: int, tolerance_seconds: int = 3) -> Optional[Dict[str, Any]]:
        """Return a tick near `seconds` ago only if enough real history exists.

        Stricter version: check that the oldest item in the window is actually
        at least `seconds` old relative to `now_ms`.
        """
        if not self.items:
            return None
        
        # Check window duration
        oldest_ts = int(self.items[0].get("ts_ms", 0))
        if now_ms - oldest_ts < seconds * 1000:
            return None

        target = now_ms - seconds * 1000
        oldest_allowed = now_ms - max(0, seconds - tolerance_seconds) * 1000
        
        # We need items that are at least 'seconds - tolerance' old.
        candidates = [x for x in self.items if int(x.get("ts_ms", 0)) <= oldest_allowed]
        if not candidates:
            return None
            
        return min(candidates, key=lambda x: abs(int(x.get("ts_ms", 0)) - target))


class FeatureEngine:
    def __init__(self):
        self.dota = RollingWindow(300)
        self.market = RollingWindow(300)

    def add_dota(self, tick: Dict[str, Any]):
        self.dota.add(tick)

    def add_market(self, tick: Dict[str, Any]):
        self.market.add(tick)

    @staticmethod
    def _score_diff(t: Dict[str, Any]) -> int:
        return int(t.get("radiant_score", 0)) - int(t.get("dire_score", 0))

    def compute(self, dota_now: Dict[str, Any], market_now: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        now_ms = dota_now["ts_ms"]

        d2 = self.dota.closest_ago(now_ms, 2, tolerance_seconds=1)
        d5 = self.dota.closest_ago(now_ms, 5, tolerance_seconds=1)
        d10 = self.dota.closest_ago(now_ms, 10)
        d30 = self.dota.closest_ago(now_ms, 30)
        d60 = self.dota.closest_ago(now_ms, 60)
        d180 = self.dota.closest_ago(now_ms, 180)

        m2 = self.market.closest_ago(market_now["ts_ms"], 2, tolerance_seconds=1)
        m5 = self.market.closest_ago(market_now["ts_ms"], 5, tolerance_seconds=1)
        m10 = self.market.closest_ago(market_now["ts_ms"], 10)
        m30 = self.market.closest_ago(market_now["ts_ms"], 30)
        m60 = self.market.closest_ago(market_now["ts_ms"], 60)

        if not d60 or not m60:
            return None

        nw_now = float(dota_now.get("nw_diff", 0.0))
        score_now = self._score_diff(dota_now)
        mid_now = float(market_now.get("mid", 0.0))
        bldg_now = int(dota_now.get("building_state", 0))

        f = {
            "match_key": dota_now.get("match_key", ""),
            "game_time": float(dota_now.get("game_time", 0.0)),
            "nw_diff": nw_now,
            "nw_diff_pct": float(dota_now.get("nw_diff_pct", 0.0)),
            "score_diff": score_now,
            "building_state": bldg_now,
            "mid": mid_now,
            "spread": float(market_now.get("spread", 1.0)),
            "ask": float(market_now.get("best_ask", 1.0)),
            "bid": float(market_now.get("best_bid", 0.0)),
            "ask_depth": float(market_now.get("ask_depth", 0.0)),
            "bid_depth": float(market_now.get("bid_depth", 0.0)),
            "radiant_mid_direct": float(market_now.get("radiant_mid_direct", mid_now)),
            "radiant_mid_inverse": float(market_now.get("radiant_mid_inverse", mid_now)),
            "combined_mid_disagreement": float(market_now.get("combined_mid_disagreement", 0.0)),
            "radiant_best_bid": float(market_now.get("radiant_best_bid", market_now.get("best_bid", 0.0))),
            "radiant_best_ask": float(market_now.get("radiant_best_ask", market_now.get("best_ask", 1.0))),
            "dire_best_bid": float(market_now.get("dire_best_bid", 0.0)),
            "dire_best_ask": float(market_now.get("dire_best_ask", 1.0)),
            "radiant_spread": float(market_now.get("radiant_spread", market_now.get("spread", 1.0))),
            "dire_spread": float(market_now.get("dire_spread", market_now.get("spread", 1.0))),
            "radiant_ask_depth": float(market_now.get("radiant_ask_depth", market_now.get("ask_depth", 0.0))),
            "radiant_bid_depth": float(market_now.get("radiant_bid_depth", market_now.get("bid_depth", 0.0))),
            "dire_ask_depth": float(market_now.get("dire_ask_depth", 0.0)),
            "dire_bid_depth": float(market_now.get("dire_bid_depth", 0.0)),
        }

        for sec, d_old in ((2, d2), (5, d5), (10, d10), (30, d30), (60, d60), (180, d180)):
            if d_old:
                f[f"nw_change_{sec}s"] = nw_now - float(d_old.get("nw_diff", 0.0))
                f[f"nw_change_{sec}s_pct"] = float(dota_now.get("nw_diff_pct", 0.0)) - float(d_old.get("nw_diff_pct", 0.0))
                f[f"score_change_{sec}s"] = score_now - self._score_diff(d_old)
                # If bitmask changed, a building fell. 1 means changed, 0 means unchanged.
                old_bldg = int(d_old.get("building_state", 0))
                f[f"building_change_{sec}s"] = 1 if (bldg_now != old_bldg and old_bldg != 0) else 0
            else:
                f[f"nw_change_{sec}s"] = 0.0
                f[f"nw_change_{sec}s_pct"] = 0.0
                f[f"score_change_{sec}s"] = 0
                f[f"building_change_{sec}s"] = 0

        for sec, m_old in ((2, m2), (5, m5), (10, m10), (30, m30), (60, m60)):
            f[f"market_change_{sec}s"] = mid_now - float(m_old.get("mid", mid_now)) if m_old else 0.0

        return f
