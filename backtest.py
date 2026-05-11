"""
Backtest: replay dota_ticks + market_ticks through current SignalEngine.
Compares new signal output vs original run, simulates taker fills, estimates PnL.
"""
import os, sys, sqlite3, bisect
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
# Mirror current .env config so the backtest uses the same trigger gates
os.environ["SIGNAL_MIN_EDGE"]               = "0.04"
os.environ["BLOCKED_TRIGGERS"]              = "SLOW_BLEED,FIGHT_EVENT,LEAD_FLIP_EVENT,STRUCTURE_EVENT"
os.environ["ENABLED_TRIGGERS"]              = "FIGHT_GAP,LEAD_FLIP_GAP,MARKET_CONFIRM,STRUCTURE_GAP,KILL_UNSEEN,NW_SURGE,OVERREACTION"
os.environ["TRIGGER_MINUTE_WINDOWS"]        = "FIGHT_GAP:8-45,LEAD_FLIP_GAP:12-40,MARKET_CONFIRM:10-45,STRUCTURE_GAP:10-45,KILL_UNSEEN:8-45,NW_SURGE:15-45,OVERREACTION:5-45"
os.environ["SIGNAL_MAX_ADVERSE_TREND_30S"]  = "0.02"

from core.features import FeatureEngine
from core.signals import SignalEngine
from core.market import combine_binary_books

GAMES = [
    {
        "name": "G1", "db": "data/1win_pari_g1.sqlite",
        "radiant_token": "74998310881290739392918170902879306286233744638879268738919090905932120366324",
        "dire_token":    "70347395524393779469493680391299369304316720284512794724445180423011761114165",
    },
    {
        "name": "G2", "db": "data/1win_pari_g2.sqlite",
        "radiant_token": "47625441297314461057077645727754264216244555280948560109804310553137263770263",
        "dire_token":    "57026843702394568915654625917402236159662865883159051302086816685884289545931",
    },
    {
        "name": "G3", "db": "data/1win_pari_g3.sqlite",
        "radiant_token": "14082266884467670274043702622681498600675941864859148613356376458056888253905",
        "dire_token":    "39003960489463622267960758033797773112117778420142043276598674855608515962197",
    },
]

TAKER_TRIGGERS = {"FIGHT_GAP", "LEAD_FLIP_GAP", "STRUCTURE_GAP", "MARKET_CONFIRM", "KILL_UNSEEN", "OVERREACTION"}
ORDER_SIZE_BASE = 20.0  # $ — matches RiskEngine default


def _load_ticks(db_path, radiant_token, dire_token):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Find the primary match: the one with the most ticks (ignore small leading fragments)
    c.execute("SELECT match_key, COUNT(*) as n FROM dota_ticks GROUP BY match_key ORDER BY n DESC LIMIT 1")
    primary_match = c.fetchone()[0]

    c.execute("SELECT * FROM dota_ticks WHERE match_key=? ORDER BY ts_ms", (primary_match,))
    cols = [d[0] for d in c.description]
    dota = [dict(zip(cols, r)) for r in c.fetchall()]

    # Market ticks: use time window of primary match for correct terminal price
    t_min = dota[0]["ts_ms"]
    t_max = dota[-1]["ts_ms"]

    c.execute("SELECT * FROM market_ticks WHERE token_id=? AND ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
              (radiant_token, t_min - 5000, t_max + 30000))
    cols = [d[0] for d in c.description]
    r_ticks = [dict(zip(cols, r)) for r in c.fetchall()]

    c.execute("SELECT * FROM market_ticks WHERE token_id=? AND ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
              (dire_token, t_min - 5000, t_max + 30000))
    d_ticks = [dict(zip(cols, r)) for r in c.fetchall()]

    # Original signals (from primary match only)
    c.execute("SELECT ts_ms, trigger, trigger_strength, side, edge, game_time, expected_move FROM signals "
              "WHERE match_key=? ORDER BY ts_ms", (primary_match,))
    orig_sigs = c.fetchall()

    conn.close()
    return dota, r_ticks, d_ticks, orig_sigs, primary_match


def _latest_before(ticks, ts_ms):
    """Binary search: latest tick with ts_ms <= ts_ms."""
    lo, hi = 0, len(ticks) - 1
    idx = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ticks[mid]["ts_ms"] <= ts_ms:
            idx = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ticks[idx] if idx >= 0 else None


def _future_mid(ticks, ts_ms, seconds):
    """Mid price N seconds after ts_ms."""
    target = ts_ms + seconds * 1000
    t = _latest_before(ticks, target)
    return float(t["mid"]) if t else None


def _order_size(mid, trigger_strength, trigger):
    """Approximate RiskEngine.order_size() logic."""
    health = 1.0  # full health in backtest
    if trigger == "OVERREACTION":
        mult = 0.1 * health
    elif trigger_strength == "STRONG":
        mult = 1.0 * health
    elif trigger_strength == "NORMAL":
        mult = 0.5 * health
    else:  # WEAK
        mult = 0.25 * health
    size_usd = ORDER_SIZE_BASE * mult
    if mid < 0.10:
        size_usd = min(size_usd, 2.0)
    elif mid > 0.90:
        size_usd = min(size_usd, 2.0)
    return round(size_usd, 2)


def _sim_fill(book, side, entry_price):
    """Return fill_price if taker order would fill, else None."""
    if side == "BUY_RADIANT_YES":
        ask = float(book.get("radiant_best_ask", 1.0))
        depth = float(book.get("radiant_ask_depth", 0.0))
    else:
        ask = float(book.get("dire_best_ask", 1.0))
        depth = float(book.get("dire_ask_depth", 0.0))
    if ask <= entry_price and depth > 0:
        return ask
    return None


def backtest_game(game):
    dota, r_ticks, d_ticks, orig_sigs, match_key = _load_ticks(
        game["db"], game["radiant_token"], game["dire_token"]
    )
    game["_match_key"] = match_key

    # Merge market timeline for PnL lookups
    all_market_by_ts = {}
    for t in r_ticks:
        all_market_by_ts[t["ts_ms"]] = t
    market_ts_sorted = sorted(r_ticks, key=lambda x: x["ts_ms"])

    features = FeatureEngine()
    eng = SignalEngine()

    signals = []
    r_book, d_book = {}, {}

    r_idx = d_idx = 0

    for dota_tick in dota:
        ts = dota_tick["ts_ms"]

        # Advance radiant book pointer
        while r_idx + 1 < len(r_ticks) and r_ticks[r_idx + 1]["ts_ms"] <= ts:
            r_idx += 1
        while d_idx + 1 < len(d_ticks) and d_ticks[d_idx + 1]["ts_ms"] <= ts:
            d_idx += 1

        if r_idx < 0 or d_idx < 0 or not r_ticks or not d_ticks:
            continue
        r_book = r_ticks[r_idx] if r_ticks else {}
        d_book = d_ticks[d_idx] if d_ticks else {}
        if not r_book or not d_book:
            continue

        combined = combine_binary_books(r_book, d_book, ts_ms=ts)

        with patch("time.time", return_value=ts / 1000.0):
            features.add_dota(dota_tick)
            features.add_market(combined)
            f = features.compute(dota_tick, combined)
            if f is None:
                continue
            f["radiant_token_id"] = game["radiant_token"]
            f["dire_token_id"]    = game["dire_token"]
            f["snapshot_score_delta"] = features._snapshot_score_delta
            f["snapshot_nw_delta"]    = features._snapshot_nw_delta
            f["snapshot_gt_jump"]     = features._snapshot_gt_jump
            f["game_time_stale"]      = features._stale_game_time

            sig = eng.generate(f, has_open_orders=True)

        if sig is None:
            continue

        trigger  = sig["trigger"]
        strength = sig["trigger_strength"]
        side     = sig["side"]
        is_taker = trigger in TAKER_TRIGGERS
        mid      = float(f.get("mid", 0.5))

        if is_taker:
            if side == "BUY_RADIANT_YES":
                ask = float(combined.get("radiant_best_ask", 1.0))
                entry = ask + 0.001
            else:
                ask = float(combined.get("dire_best_ask", 1.0))
                entry = ask + 0.001
        else:
            if side == "BUY_RADIANT_YES":
                entry = float(combined.get("radiant_best_bid", 0.0)) + 0.001
            else:
                entry = float(combined.get("dire_best_bid", 0.0)) + 0.001

        entry = round(min(max(entry, 0.01), 0.99), 4)
        fill_price = _sim_fill(combined, side, entry)
        size_usd = _order_size(mid, strength, trigger)

        # Mark-to-market horizons using the relevant token's ticks
        ref_ticks = r_ticks if side == "BUY_RADIANT_YES" else d_ticks
        m15 = _future_mid(ref_ticks, ts, 15)
        m30 = _future_mid(ref_ticks, ts, 30)
        m60 = _future_mid(ref_ticks, ts, 60)

        pnl = {}
        if fill_price is not None:
            tokens = size_usd / fill_price
            for label, mx in [("15s", m15), ("30s", m30), ("60s", m60)]:
                if mx is not None:
                    pnl[f"pnl_{label}"] = round((mx - fill_price) * tokens, 4)

        signals.append({
            "ts_ms": ts, "game_time": dota_tick.get("game_time"),
            "trigger": trigger, "strength": strength,
            "side": side, "mid": round(mid, 4),
            "edge": round(sig["edge"], 4),
            "entry": entry,
            "filled": fill_price is not None,
            "fill_price": fill_price,
            "size_usd": size_usd,
            "ref_ticks_last": ref_ticks[-1] if ref_ticks else None,
            **pnl,
        })

    # Terminal price: last known market mid for each token
    terminal_r = float(r_ticks[-1]["mid"]) if r_ticks else None
    terminal_d = float(d_ticks[-1]["mid"]) if d_ticks else None

    return signals, orig_sigs, terminal_r, terminal_d


def print_report(game, signals, orig_sigs, terminal_r, terminal_d):
    name = game["name"]
    print(f"\n{'='*60}")
    print(f"  {name}  ({game['db']})")
    r_outcome = "?" if terminal_r is None else (f"WIN (final mid={terminal_r:.3f})" if terminal_r > 0.5 else f"LOSE (final mid={terminal_r:.3f})")
    print(f"  Radiant outcome: {r_outcome}")
    print(f"{'='*60}")

    print(f"\n[ORIGINAL RUN] {len(orig_sigs)} signals")
    for s in orig_sigs:
        ts_ms, trig, strength, side, edge, gt, exp = s
        print(f"  gt={int(gt):>5}  {trig:<18} {strength:<7} {side:<18} edge={edge:.3f}  exp={exp:.3f}")

    print(f"\n[BACKTEST]     {len(signals)} signals")
    filled = [s for s in signals if s["filled"]]
    for s in signals:
        pnl_str = ""
        if s["filled"]:
            fp = s["fill_price"]
            tokens = s["size_usd"] / fp if fp else 0
            terminal = terminal_r if s["side"] == "BUY_RADIANT_YES" else terminal_d
            t_pnl = round((terminal - fp) * tokens, 3) if terminal is not None else "?"
            p15 = s.get("pnl_15s", "?")
            p60 = s.get("pnl_60s", "?")
            pnl_str = f"  fill={fp:.3f}  pnl[15s={p15} 60s={p60} term={t_pnl}]"
        tag = "FILL" if s["filled"] else "miss"
        print(f"  gt={int(s['game_time']):>5}  {s['trigger']:<18} {s['strength']:<7} {s['side']:<18} "
              f"edge={s['edge']:.3f}  entry={s['entry']:.3f}  [{tag}]{pnl_str}")

    if signals:
        fill_rate = len(filled) / len(signals) * 100
        print(f"\n  Fill rate: {len(filled)}/{len(signals)} = {fill_rate:.0f}%")
    if filled:
        for label in ["15s", "60s"]:
            vals = [s[f"pnl_{label}"] for s in filled if f"pnl_{label}" in s]
            if vals:
                print(f"  Avg PnL {label}: ${sum(vals)/len(vals):.3f}  total=${sum(vals):.3f}")
        # Terminal PnL
        t_vals = []
        for s in filled:
            fp = s["fill_price"]
            if fp is None:
                continue
            tokens = s["size_usd"] / fp
            terminal = terminal_r if s["side"] == "BUY_RADIANT_YES" else terminal_d
            if terminal is not None:
                t_vals.append((terminal - fp) * tokens)
        if t_vals:
            print(f"  Avg PnL term: ${sum(t_vals)/len(t_vals):.3f}  total=${sum(t_vals):.3f}")

    # Diff vs original
    new_triggers = {(s["game_time"], s["trigger"]) for s in signals}
    old_triggers = {(int(s[5]), s[1]) for s in orig_sigs}
    added   = new_triggers - old_triggers
    removed = old_triggers - new_triggers
    if added:
        print(f"\n  NEW (not in original): {sorted(added)}")
    if removed:
        print(f"  DROPPED (was in original): {sorted(removed)}")
    if not added and not removed and orig_sigs:
        print("\n  Signal set identical to original run.")


if __name__ == "__main__":
    for game in GAMES:
        signals, orig_sigs, terminal_r, terminal_d = backtest_game(game)
        print_report(game, signals, orig_sigs, terminal_r, terminal_d)
    print()
