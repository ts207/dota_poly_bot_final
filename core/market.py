# core/market.py
from typing import Dict, Any, Optional
import time


def combine_binary_books(
    radiant_book: Dict[str, Any],
    dire_book: Dict[str, Any],
    ts_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Convert two complementary YES token books into one Radiant-probability view.

    Radiant YES book gives direct Radiant prices.
    Dire YES book gives inverse Radiant prices: Radiant probability ≈ 1 - Dire YES.

    This combined view is for signal/features only. Execution still uses the real
    target token book: Radiant YES for positive signals, Dire YES for negative signals.
    """
    r_ts = int(radiant_book.get("ts_ms", 0) or 0)
    d_ts = int(dire_book.get("ts_ms", 0) or 0)
    if ts_ms is not None:
        ts = int(ts_ms)
    elif r_ts and d_ts:
        # Use the older timestamp so the combined book cannot look fresh when
        # either leg of the binary pair is stale. Keep both leg timestamps below
        # for downstream diagnostics.
        ts = min(r_ts, d_ts)
    else:
        ts = r_ts or d_ts or int(time.time() * 1000)

    r_bid = float(radiant_book.get("best_bid", 0.0))
    r_ask = float(radiant_book.get("best_ask", 1.0))
    d_bid = float(dire_book.get("best_bid", 0.0))
    d_ask = float(dire_book.get("best_ask", 1.0))

    # Conservative synthetic Radiant bid/ask from the Dire YES book.
    # Selling/shorting Dire YES is not directly the same as buying Radiant YES,
    # but these inversions are useful for estimating a fair combined probability.
    inv_r_bid = max(0.0, min(1.0, 1.0 - d_ask))
    inv_r_ask = max(0.0, min(1.0, 1.0 - d_bid))

    direct_mid = (r_bid + r_ask) / 2.0
    inverse_mid = (inv_r_bid + inv_r_ask) / 2.0
    combined_mid = (direct_mid + inverse_mid) / 2.0

    # Effective visible spread in Radiant probability space. Use conservative
    # executable direct spread for risk and signal thresholds.
    direct_spread = max(0.0, r_ask - r_bid)
    inverse_spread = max(0.0, inv_r_ask - inv_r_bid)
    combined_spread = max(direct_spread, inverse_spread)

    return {
        "ts_ms": ts,
        "radiant_ts_ms": r_ts,
        "dire_ts_ms": d_ts,
        "leg_ts_skew_ms": abs(r_ts - d_ts) if r_ts and d_ts else None,
        "best_bid": r_bid,
        "best_ask": r_ask,
        "mid": combined_mid,
        "spread": combined_spread,
        "bid_depth": float(radiant_book.get("bid_depth", 0.0)),
        "ask_depth": float(radiant_book.get("ask_depth", 0.0)),
        "radiant_mid_direct": direct_mid,
        "radiant_mid_inverse": inverse_mid,
        "radiant_best_bid": r_bid,
        "radiant_best_ask": r_ask,
        "dire_best_bid": d_bid,
        "dire_best_ask": d_ask,
        "dire_mid": float(dire_book.get("mid", (d_bid + d_ask) / 2.0)),
        "radiant_spread": direct_spread,
        "dire_spread": max(0.0, d_ask - d_bid),
        "synthetic_radiant_bid": inv_r_bid,
        "synthetic_radiant_ask": inv_r_ask,
        "combined_mid_disagreement": abs(direct_mid - inverse_mid),
        "radiant_ask_depth": float(radiant_book.get("ask_depth", 0.0)),
        "radiant_bid_depth": float(radiant_book.get("bid_depth", 0.0)),
        "dire_ask_depth": float(dire_book.get("ask_depth", 0.0)),
        "dire_bid_depth": float(dire_book.get("bid_depth", 0.0)),
    }
