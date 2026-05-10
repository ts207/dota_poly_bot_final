import sqlite3
import pandas as pd
import os

# Config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data/dota_poly_collection.sqlite")

def get_high_conviction_trigger(row):
    # Re-bucket based on stricter rules
    score_10s = abs(row['score_change_10s'])
    nw_10s = abs(row['nw_change_10s'])
    mkt_10s = abs(row['market_change_10s'])
    
    # We require market to be flat (< 1 cent)
    is_flat = mkt_10s < 0.01
    
    if is_flat:
        if score_10s >= 2 and nw_10s >= 2000:
            return "L_STRONG_GAP"
        if score_10s >= 2:
            return "L_FIGHT (2+ Kills)"
        if nw_10s >= 2000:
            return "L_ECON (2k+ NW)"
    
    # Otherwise check underreaction
    if score_10s >= 2 and nw_10s >= 2000: return "UNDERREACTION_STRONG"
    if score_10s >= 1 or nw_10s >= 1000: return "UNDERREACTION_WEAK"
    
    return "NOISE"

def main():
    if not os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)

    signals = pd.read_sql_query("""
    SELECT id, ts_ms, match_key, target_token_id, score_change_10s, nw_change_10s, market_change_10s
    FROM signals
    """, conn)
    # Note: I'll need 'mid_at_signal' which might be in signal_data if not a column.
    # Actually I'll join with market_ticks for the 'before' price.

    ticks = pd.read_sql_query("""
    SELECT ts_ms, token_id, mid
    FROM market_ticks
    WHERE token_id != 'COMBINED_RADIANT'
    ORDER BY ts_ms
    """, conn)
    conn.close()

    rows = []
    for _, s in signals.iterrows():
        token_ticks = ticks[ticks.token_id == str(s['target_token_id'])]
        before = token_ticks[token_ticks.ts_ms <= s['ts_ms']].tail(1)
        if before.empty: continue
        
        base_mid = float(before.iloc[0].mid)
        trigger = get_high_conviction_trigger(s)
        
        row = {'match_key': s['match_key'], 'trigger': trigger, 'base_mid': base_mid}
        for h in [15, 30, 60]:
            future = token_ticks[token_ticks.ts_ms >= s['ts_ms'] + h * 1000].head(1)
            if not future.empty:
                move = float(future.iloc[0].mid) - base_mid
                row[f'move_{h}s'] = move
                row[f'win_{h}s'] = move > 0
            else:
                row[f'move_{h}s'], row[f'win_{h}s'] = None, None
        rows.append(row)

    df = pd.DataFrame(rows)
    summary = df.groupby(['match_key', 'trigger']).agg({
        'win_30s': ['count', 'mean'],
        'move_30s': ['mean']
    }).sort_values(['match_key', ('win_30s', 'mean')], ascending=[True, False])
    
    print("\n=== HIGH CONVICTION AUDIT BY MATCH ===")
    print(summary)

if __name__ == "__main__":
    main()
