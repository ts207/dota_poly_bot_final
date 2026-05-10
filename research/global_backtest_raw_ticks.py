import sqlite3
import pandas as pd
import numpy as np
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data/dota_poly_collection.sqlite")

def main():
    if not os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)

    print("Loading data and mapping tokens...")
    sig_map = pd.read_sql_query("SELECT DISTINCT match_key, target_token_id, side FROM signals", conn)
    mapping = {}
    for _, row in sig_map.iterrows():
        mk = row['match_key']
        if mk not in mapping: mapping[mk] = {}
        if 'RADIANT' in row['side']: mapping[mk]['RADIANT'] = row['target_token_id']
        else: mapping[mk]['DIRE'] = row['target_token_id']

    dota = pd.read_sql_query("SELECT * FROM dota_ticks ORDER BY match_key, ts_ms", conn)
    market = pd.read_sql_query("SELECT * FROM market_ticks WHERE token_id != 'COMBINED_RADIANT' ORDER BY token_id, ts_ms", conn)
    conn.close()

    results = []
    matches = dota.match_key.unique()

    for mk in matches:
        if mk not in mapping or 'RADIANT' not in mapping[mk] or 'DIRE' not in mapping[mk]:
            continue
            
        m_ticks = dota[dota.match_key == mk].copy().sort_values('ts_ms')
        rad_token = mapping[mk]['RADIANT']
        dire_token = mapping[mk]['DIRE']

        m_rad = market[market.token_id == rad_token].sort_values('ts_ms')
        m_dire = market[market.token_id == dire_token].sort_values('ts_ms')
        
        # Merge dota with BOTH markets
        merged = pd.merge_asof(m_ticks, m_rad[['ts_ms', 'mid', 'best_bid', 'best_ask']], on='ts_ms', direction='backward')
        merged = pd.merge_asof(merged, m_dire[['ts_ms', 'mid', 'best_bid', 'best_ask']], on='ts_ms', direction='backward', suffixes=('_rad', '_dire'))
        
        # Calculate windows for both
        for offset in [10000, 60000]:
            merged_off = merged[['ts_ms', 'nw_diff', 'radiant_score', 'dire_score', 'mid_rad', 'mid_dire']].copy()
            merged_off['ts_ms'] = merged_off['ts_ms'] + offset
            merged = pd.merge_asof(merged, merged_off, on='ts_ms', direction='backward', suffixes=('', f'_{offset}ms'))

        merged['nw_10s'] = merged['nw_diff'] - merged['nw_diff_10000ms']
        merged['score_diff_10s'] = (merged['radiant_score'] - merged['dire_score']) - (merged['radiant_score_10000ms'] - merged['dire_score_10000ms'])
        merged['rad_mkt_10s'] = merged['mid_rad'] - merged['mid_rad_10000ms']
        merged['dire_mkt_10s'] = merged['mid_dire'] - merged['mid_dire_10000ms']
        merged['rad_vol_60s'] = abs(merged['mid_rad'] - merged['mid_rad_60000ms'])
        
        for idx, row in merged.iterrows():
            s10_raw, n10_raw = row['score_diff_10s'], row['nw_10s']
            s10_abs, n10_abs = abs(s10_raw), abs(n10_raw)
            if s10_abs < 2 or n10_abs < 2000: continue
            
            # Side detection
            if s10_raw > 0 or n10_raw > 2000:
                side, target_token = "RADIANT", rad_token
                mkt_move = row['rad_mkt_10s']
                cur_bid, cur_ask = row['best_bid_rad'], row['best_ask_rad']
            else:
                side, target_token = "DIRE", dire_token
                mkt_move = row['dire_mkt_10s']
                cur_bid, cur_ask = row['best_bid_dire'], row['best_ask_dire']

            if pd.isna(cur_bid) or pd.isna(cur_ask): continue
            is_snowball = abs(row['nw_diff']) >= 10000 and row['rad_vol_60s'] >= 0.03 and row['game_time'] >= 1200
            
            trigger = None
            # M_STRONG_CONFIRM
            if 0.01 <= mkt_move <= 0.05:
                trigger = "M_STRONG_CONFIRM"
                entry_taker = min(cur_ask + 0.01, 0.99)
                entry_maker = cur_bid + 0.001
            # L_STRONG_GAP
            elif abs(mkt_move) < 0.01:
                trigger = "L_STRONG_GAP"
                entry_maker = cur_bid + 0.001
                # Fill Proxy
                f_window = market[(market.token_id == target_token) & (market.ts_ms >= row['ts_ms']) & (market.ts_ms <= row['ts_ms'] + 3000)]
                if not (not f_window.empty and (f_window.best_ask.min() <= entry_maker or f_window.best_bid.min() <= entry_maker)):
                    continue
            else: continue

            if trigger:
                res_base = {'match': mk, 'trigger': trigger, 'is_snowball': is_snowball}
                # Taker Exit at 120s
                exit_snap = market[(market.token_id == target_token) & (market.ts_ms >= row['ts_ms'] + 120000)].head(1)
                if not exit_snap.empty:
                    exit_p = float(exit_snap.iloc[0].best_bid)
                    if trigger == "M_STRONG_CONFIRM":
                        results.append({**res_base, 'mode': 'TAKER', 'pnl_120s': exit_p - entry_taker})
                        results.append({**res_base, 'mode': 'MAKER', 'pnl_120s': exit_p - entry_maker})
                    else:
                        results.append({**res_base, 'mode': 'MAKER', 'pnl_120s': exit_p - entry_maker})

    df = pd.DataFrame(results)
    if df.empty:
        print("No signals found in refined audit.")
        return

    print("\n=== REFINED GLOBAL TICK BACKTEST (120s PnL) ===")
    summary = df.groupby(['trigger', 'mode', 'is_snowball']).agg({'pnl_120s': ['count', 'mean']}).round(4)
    print(summary)

if __name__ == "__main__":
    main()
