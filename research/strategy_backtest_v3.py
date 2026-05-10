import sqlite3
import pandas as pd
import os
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data/dota_poly_collection.sqlite")

def get_signal_profile(row):
    # This matches core/signals.py logic
    score_10s_raw = row['score_change_10s']
    nw_10s_raw = row['nw_change_10s']
    mkt_10s_raw = row['market_change_10s']
    
    score_10s = abs(score_10s_raw)
    nw_10s = abs(nw_10s_raw)
    strong_shock = score_10s >= 2 and nw_10s >= 2000
    
    shock_dir = 1 if (score_10s_raw > 0 or nw_10s_raw > 0) else -1
    
    # 1. M_STRONG_CONFIRM
    market_confirmed = (
        (shock_dir == 1 and 0.01 <= mkt_10s_raw <= 0.05) or
        (shock_dir == -1 and -0.05 <= mkt_10s_raw <= -0.01)
    )
    if strong_shock and market_confirmed:
        return "M_STRONG_CONFIRM"
        
    # 2. L_STRONG_GAP
    if strong_shock and abs(mkt_10s_raw) < 0.01:
        return "L_STRONG_GAP"
        
    # 3. Fallbacks (Standard Under-reaction)
    if score_10s >= 2: return "FIGHT"
    if nw_10s >= 2000: return "ECON"
    if score_10s >= 1: return "KILL_EVENT"
    
    return "SLOW_BLEED"

def main():
    if not os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)

    signals = pd.read_sql_query("""
    SELECT id, ts_ms, target_token_id, score_change_10s, nw_change_10s, market_change_10s
    FROM signals
    """, conn)

    ticks = pd.read_sql_query("""
    SELECT ts_ms, token_id, best_bid, best_ask, mid
    FROM market_ticks
    WHERE token_id != 'COMBINED_RADIANT'
    ORDER BY ts_ms
    """, conn)
    conn.close()

    results = []
    for _, s in signals.iterrows():
        profile = get_signal_profile(s)
        if profile == "OTHER": continue
        
        token_ticks = ticks[ticks.token_id == str(s['target_token_id'])]
        snap = token_ticks[token_ticks.ts_ms <= s['ts_ms']].tail(1)
        if snap.empty: continue
        
        snap = snap.iloc[0]
        # Entry Price Simulation
        if profile == "M_STRONG_CONFIRM":
            # Taker with 1 cent overhead
            entry = min(float(snap.best_ask) + 0.01, 0.99)
            filled = True
        else:
            # Maker Bid + 0.001
            entry = float(snap.best_bid) + 0.001
            # Maker Fill Proxy: Did ask or bid touch our entry in 3s?
            fill_window = token_ticks[
                (token_ticks.ts_ms >= s["ts_ms"]) &
                (token_ticks.ts_ms <= s["ts_ms"] + 3000)
            ]
            filled = not fill_window.empty and (
                fill_window.best_ask.min() <= entry or 
                fill_window.best_bid.min() <= entry
            )
            
        if not filled: continue
            
        row = {'trigger': profile, 'entry': entry, 'base_mid': snap.mid}
        
        for h in [30, 60, 120]:
            future = token_ticks[token_ticks.ts_ms >= s['ts_ms'] + h * 1000].head(1)
            if not future.empty:
                # Exit at Bid (Liquidation)
                exit_p = float(future.iloc[0].best_bid)
                pnl = exit_p - entry
                row[f'pnl_{h}s'] = pnl
            else:
                row[f'pnl_{h}s'] = np.nan
        results.append(row)

    df = pd.DataFrame(results)
    if df.empty:
        print("No strategy-match signals found in history.")
        return

    print("\n=== V3 HYBRID STRATEGY BACKTEST (REALIZED PNL) ===")
    summary = df.groupby('trigger').agg({
        'pnl_30s': ['count', 'mean', 'sum'],
        'pnl_120s': ['mean']
    }).round(4)
    print(summary)

if __name__ == "__main__":
    main()
