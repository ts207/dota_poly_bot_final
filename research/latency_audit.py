import pandas as pd
import sqlite3
import numpy as np
from datetime import datetime
import os

# Config
SHADOW_LOG = "/home/irene/dota_poly_bot_final/data/shadow_signals.csv"
DB_PATH = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"

def analyze_latency_pnl():
    if not os.path.exists(SHADOW_LOG):
        print("No shadow signals found yet.")
        return

    df = pd.read_csv(SHADOW_LOG)
    if df.empty:
        print("Shadow log is empty.")
        return

    conn = sqlite3.connect(DB_PATH)
    
    # Load market ticks for PnL calculation
    # We use a broad range to cover exit horizons
    min_ts = int(df['ts'].min() * 1000)
    max_ts = int(df['ts'].max() * 1000) + 120000 # +120s for exit window
    
    ticks = pd.read_sql(f"""
        SELECT ts_ms, mid 
        FROM market_ticks 
        WHERE ts_ms BETWEEN {min_ts} AND {max_ts}
        ORDER BY ts_ms ASC
    """, conn)
    conn.close()

    if ticks.empty:
        print("No market ticks found for the signal period.")
        return

    results = []
    
    for _, row in df.iterrows():
        sig_ts_ms = int(row['ts'] * 1000)
        side = row['side']
        entry_price = row['fair'] - row['edge'] # This is 'entry_price_target'
        
        # Find price at horizons
        pnl_horizons = {}
        for horizon in [15, 30, 60]:
            target_ts = sig_ts_ms + (horizon * 1000)
            # Find closest tick within 2s of horizon
            future_ticks = ticks[(ticks['ts_ms'] >= target_ts) & (ticks['ts_ms'] <= target_ts + 2000)]
            if not future_ticks.empty:
                exit_price = future_ticks.iloc[0]['mid']
                # PnL = exit - entry (if BUY RADIANT)
                # If side is DIRE, we need to adjust, but signal side is RADIANT/DIRE
                pnl = (exit_price - entry_price) if side == "RADIANT" else ((1.0 - exit_price) - entry_price)
                pnl_horizons[f'pnl_{horizon}s'] = pnl
            else:
                pnl_horizons[f'pnl_{horizon}s'] = np.nan
        
        results.append({
            'trigger': row['trigger'],
            'action': row['action'],
            **pnl_horizons
        })

    results_df = pd.DataFrame(results)
    
    # Group by trigger and action
    summary = results_df.groupby(['trigger', 'action']).agg({
        'pnl_15s': ['count', 'mean'],
        'pnl_30s': ['mean'],
        'pnl_60s': ['mean']
    })
    
    print("\n=== Latency PnL Audit Report ===")
    print(summary)

if __name__ == "__main__":
    analyze_latency_pnl()
