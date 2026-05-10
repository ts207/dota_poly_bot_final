import sqlite3
import pandas as pd
import numpy as np
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data/dota_poly_collection.sqlite")

def main():
    if not os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)

    print("Loading raw ticks (this may take a moment)...")
    dota = pd.read_sql_query("SELECT * FROM dota_ticks ORDER BY match_key, ts_ms", conn)
    market = pd.read_sql_query("SELECT * FROM market_ticks WHERE token_id != 'COMBINED_RADIANT' ORDER BY token_id, ts_ms", conn)
    conn.close()

    results = []
    matches = dota.match_key.unique()

    for mk in matches:
        m_ticks = dota[dota.match_key == mk].copy()
        m_ticks['game_min'] = m_ticks['game_time'] / 60
        
        # Calculate 10s features (approximating with 10,000ms window)
        # Using shift/rolling is faster than per-tick lookups
        m_ticks = m_ticks.sort_values('ts_ms')
        
        # We need to map market ticks to each dota tick
        # This is the slow part, we'll use merge_asof
        m_ticks['target_token_id'] = m_ticks.apply(lambda x: "RADIANT" if x['radiant_score'] > 0 else "RADIANT", axis=1) # Mock token mapping
        
        # For a proper backtest we'd need the real token mapping per match, 
        # but since we only have one market per match in the DB usually, we'll use the most common one.
        # Let's just use the first market_id/token_id we find for that match period.
        
        m_market = market[(market.ts_ms >= m_ticks.ts_ms.min()) & (market.ts_ms <= m_ticks.ts_ms.max())].copy()
        if m_market.empty: continue
        
        # Use a single token_id for simplicity in this global audit
        tid = m_market.token_id.iloc[0]
        m_market = m_market[m_market.token_id == tid].sort_values('ts_ms')

        # Merge dota and market ticks
        merged = pd.merge_asof(m_ticks, m_market[['ts_ms', 'mid', 'best_bid', 'best_ask']], on='ts_ms', direction='backward')
        
        # Calculate changes over 10s (10000ms)
        # Using a fixed step lookup for speed
        for offset in [10000, 60000]:
            merged_off = merged[['ts_ms', 'nw_diff', 'radiant_score', 'dire_score', 'mid']].copy()
            merged_off['ts_ms'] = merged_off['ts_ms'] + offset
            merged = pd.merge_asof(merged, merged_off, on='ts_ms', direction='backward', suffixes=('', f'_{offset}ms'))

        merged['nw_10s'] = merged['nw_diff'] - merged['nw_diff_10000ms']
        merged['score_10s'] = (merged['radiant_score'] + merged['dire_score']) - (merged['radiant_score_10000ms'] + merged['dire_score_10000ms'])
        merged['mkt_10s'] = merged['mid'] - merged['mid_10000ms']
        merged['mkt_60s'] = merged['mid'] - merged['mid_60000ms']
        
        for idx, row in merged.iterrows():
            # Apply V3 Logic
            s10_raw = row['score_10s']
            n10_raw = row['nw_10s']
            m10_raw = row['mkt_10s']
            
            s10, n10 = abs(s10_raw), abs(n10_raw)
            if s10 < 2 or n10 < 2000: continue # Only Strong Shocks
            
            shock_dir = 1 if (s10_raw > 0 or n10_raw > 0) else -1
            
            # Regime
            is_snowball = abs(row['nw_diff']) >= 10000 and abs(row['mkt_60s']) >= 0.03 and row['game_time'] >= 1200
            
            trigger = None
            entry = 0
            
            # M_STRONG_CONFIRM
            m_confirmed = (shock_dir == 1 and 0.01 <= m10_raw <= 0.05) or (shock_dir == -1 and -0.05 <= m10_raw <= -0.01)
            if m_confirmed:
                trigger = "M_STRONG_CONFIRM"
                entry = min(float(row['best_ask']) + 0.01, 0.99)
                filled = True
            elif abs(m10_raw) < 0.01:
                trigger = "L_STRONG_GAP"
                entry = float(row['best_bid']) + 0.001
                # Fill Proxy (Check next 3s)
                f_window = m_market[(m_market.ts_ms >= row['ts_ms']) & (m_market.ts_ms <= row['ts_ms'] + 3000)]
                filled = not f_window.empty and (f_window.best_ask.min() <= entry or f_window.best_bid.min() <= entry)
            
            if trigger and filled:
                # Find exit at 30s
                exit_snap = m_market[m_market.ts_ms >= row['ts_ms'] + 30000].head(1)
                if not exit_snap.empty:
                    pnl = float(exit_snap.iloc[0].best_bid) - entry
                    results.append({
                        'match': mk,
                        'trigger': trigger,
                        'is_snowball': is_snowball,
                        'pnl_30s': pnl
                    })

    df = pd.DataFrame(results)
    if df.empty:
        print("No signals found in global tick audit.")
        return

    print("\n=== GLOBAL TICK-LEVEL BACKTEST (ALL MATCHES) ===")
    summary = df.groupby(['trigger', 'is_snowball']).agg({
        'pnl_30s': ['count', 'mean', 'sum']
    }).round(4)
    print(summary)
    
    print("\nBy Match (M_STRONG_CONFIRM | Snowball=True):")
    stomp_df = df[(df.trigger == "M_STRONG_CONFIRM") & (df.is_snowball == True)]
    if not stomp_df.empty:
        print(stomp_df.groupby('match').pnl_30s.mean())
    else:
        print("No snowball momentum signals found in any match.")

if __name__ == "__main__":
    main()
