import pandas as pd
import sqlite3
import numpy as np
import os
from datetime import datetime

# Config
SHADOW_LOG = "/home/irene/dota_poly_bot_final/data/shadow_signals.csv"
DB_PATH = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"

def get_lead_bucket(nw_diff):
    abs_nw = abs(nw_diff)
    if abs_nw < 5000: return "close"
    if abs_nw < 15000: return "medium"
    if abs_nw < 30000: return "stomp"
    return "dead"

def analyze_latency_deep():
    if not os.path.exists(SHADOW_LOG):
        print("No shadow signals found.")
        return

    df = pd.read_csv(SHADOW_LOG)
    if df.empty:
        print("Shadow log is empty.")
        return

    conn = sqlite3.connect(DB_PATH)
    
    # Load all relevant ticks into memory for speed
    min_ts = int(df['ts'].min() * 1000) - 5000
    max_ts = int(df['ts'].max() * 1000) + 130000
    
    ticks = pd.read_sql(f"""
        SELECT ts_ms, token_id, best_bid, best_ask 
        FROM market_ticks 
        WHERE ts_ms BETWEEN {min_ts} AND {max_ts}
          AND token_id != 'COMBINED_RADIANT'
    """, conn)
    conn.close()

    if ticks.empty:
        print("No market ticks found.")
        return

    results = []
    
    for _, row in df.iterrows():
        sig_ts_ms = int(row['ts'] * 1000)
        token_id = str(row['token_id'])
        # Side check for PnL calculation
        # Entry is always 'entry_price_target' which is ask + 0.01
        entry_price = row['fair'] - row['edge']
        
        # Filter ticks for this token
        t_ticks = ticks[ticks['token_id'] == token_id]
        
        pnl_horizons = {}
        for horizon in [15, 30, 60]:
            target_ts = sig_ts_ms + (horizon * 1000)
            # Find the best bid at that horizon (executable exit)
            future = t_ticks[t_ticks['ts_ms'] >= target_ts].sort_values('ts_ms')
            if not future.empty:
                # Exit at best_bid (if we bought YES)
                exit_price = future.iloc[0]['best_bid']
                pnl_horizons[f'pnl_{horizon}s'] = exit_price - entry_price
            else:
                pnl_horizons[f'pnl_{horizon}s'] = np.nan
        
        # Adverse excursion (max drop in 60s)
        window_60s = t_ticks[(t_ticks['ts_ms'] >= sig_ts_ms) & (t_ticks['ts_ms'] <= sig_ts_ms + 60000)]
        if not window_60s.empty:
            mae = window_60s['best_bid'].min() - entry_price
            mfe = window_60s['best_bid'].max() - entry_price
        else:
            mae, mfe = np.nan, np.nan

        results.append({
            'trigger': row['trigger'],
            'action': row['action'],
            'lead_bucket': get_lead_bucket(row['nw_diff']),
            'is_winning': (row['nw_diff'] > 0 and row['side'] == 'RADIANT') or (row['nw_diff'] < 0 and row['side'] == 'DIRE'),
            **pnl_horizons,
            'mae': mae,
            'mfe': mfe
        })

    rdf = pd.DataFrame(results)
    
    # Final deep report
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    summary = rdf.groupby(['trigger', 'action', 'lead_bucket', 'is_winning']).agg({
        'pnl_15s': ['count', 'mean'],
        'pnl_60s': ['mean'],
        'mae': 'mean',
        'mfe': 'mean'
    })
    
    print("\n=== LATENCY DEEP AUDIT (EXECUTABLE PN) ===")
    print(summary)

if __name__ == "__main__":
    analyze_latency_deep()
