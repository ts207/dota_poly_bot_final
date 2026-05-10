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
    # Get token mapping from historical signals
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

        # Get market ticks for both tokens
        m_market = market[(market.token_id.isin([rad_token, dire_token]))].copy().sort_values(['token_id', 'ts_ms'])
        
        # Merge dota with both radiant and dire market ticks
        m_rad = m_market[m_market.token_id == rad_token]
        m_dire = m_market[m_market.token_id == dire_token]
        
        # Merge dota with radiant market (primary)
        merged = pd.merge_asof(m_ticks, m_rad[['ts_ms', 'mid', 'best_bid', 'best_ask']], on='ts_ms', direction='backward')
        
        # Calculate 10s and 60s windows
        for offset in [10000, 60000]:
            merged_off = merged[['ts_ms', 'nw_diff', 'radiant_score', 'dire_score', 'mid']].copy()
            merged_off['ts_ms'] = merged_off['ts_ms'] + offset
            merged = pd.merge_asof(merged, merged_off, on='ts_ms', direction='backward', suffixes=('', f'_{offset}ms'))

        # Directional Features
        merged['nw_10s'] = merged['nw_diff'] - merged['nw_diff_10000ms']
        merged['score_diff'] = merged['radiant_score'] - merged['dire_score']
        merged['score_diff_10s'] = merged['score_diff'] - (merged['radiant_score_10000ms'] - merged['dire_score_10000ms'])
        merged['mkt_10s'] = merged['mid'] - merged['mid_10000ms']
        merged['mkt_60s'] = merged['mid'] - merged['mid_60000ms']
        
        for idx, row in merged.iterrows():
            s10_raw = row['score_diff_10s']
            n10_raw = row['nw_10s']
            m10_raw = row['mkt_10s']
            
            s10_abs, n10_abs = abs(s10_raw), abs(n10_raw)
            if s10_abs < 2 or n10_abs < 2000: continue
            
            # Which side are we buying?
            # Positive shock (Radiant kills/NW) -> Buy Radiant
            # Negative shock (Dire kills/NW) -> Buy Dire
            if s10_raw > 0 or n10_raw > 2000:
                side = "RADIANT"
                target_token = rad_token
                mkt_move = m10_raw
                cur_mid, cur_bid, cur_ask = row['mid'], row['best_bid'], row['best_ask']
            else:
                side = "DIRE"
                target_token = dire_token
                # Need Dire market price. We merge_asof for speed.
                dire_snap = m_dire[m_dire.ts_ms <= row['ts_ms']].tail(1)
                if dire_snap.empty: continue
                cur_mid, cur_bid, cur_ask = float(dire_snap.iloc[0].mid), float(dire_snap.iloc[0].best_bid), float(dire_snap.iloc[0].best_ask)
                # Market move for Dire YES is inverse of Radiant YES move (approximately)
                # But to be safe, we'd need dire_mid_10s. Let's use radiant move inverted.
                mkt_move = -m10_raw 

            is_snowball = abs(row['nw_diff']) >= 10000 and abs(row['mkt_60s']) >= 0.03 and row['game_time'] >= 1200
            
            trigger = None
            # M_STRONG_CONFIRM: Shock + same-direction move (1-5 cents)
            if 0.01 <= mkt_move <= 0.05:
                trigger = "M_STRONG_CONFIRM"
                entry = min(cur_ask + 0.01, 0.99)
                filled = True
            # L_STRONG_GAP: Dead Gap (< 1 cent move)
            elif abs(mkt_move) < 0.01:
                trigger = "L_STRONG_GAP"
                entry = cur_bid + 0.001
                f_window = m_market[(m_market.token_id == target_token) & (m_market.ts_ms >= row['ts_ms']) & (m_market.ts_ms <= row['ts_ms'] + 3000)]
                filled = not f_window.empty and (f_window.best_ask.min() <= entry or f_window.best_bid.min() <= entry)
            else:
                continue

            if trigger and filled:
                res = {'match': mk, 'trigger': trigger, 'is_snowball': is_snowball}
                for h in [30, 60, 120]:
                    exit_snap = m_market[(m_market.token_id == target_token) & (m_market.ts_ms >= row['ts_ms'] + h * 1000)].head(1)
                    res[f'pnl_{h}s'] = float(exit_snap.iloc[0].best_bid) - entry if not exit_snap.empty else np.nan
                results.append(res)

    df = pd.DataFrame(results)
    if df.empty:
        print("No signals found in hardened audit.")
        return

    print("\n=== HARDENED GLOBAL TICK BACKTEST ===")
    summary = df.groupby(['trigger', 'is_snowball']).agg({
        'pnl_30s': ['count', 'mean'],
        'pnl_120s': ['mean']
    }).round(4)
    print(summary)
    
    print("\nM_STRONG_CONFIRM | Snowball=True | By Match:")
    stomp = df[(df.trigger == "M_STRONG_CONFIRM") & (df.is_snowball == True)]
    if not stomp.empty:
        print(stomp.groupby('match').pnl_120s.mean())

if __name__ == "__main__":
    main()
