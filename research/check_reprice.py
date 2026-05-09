import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort

def check_reprice_time():
    conn = sqlite3.connect("../data/dota_poly_collection.sqlite")
    dota_df = pd.read_sql_query("SELECT ts_ms, match_key, game_time, nw_diff, radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
    market_df = pd.read_sql_query("SELECT ts_ms, mid, spread FROM market_ticks WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms", conn)
    
    df = pd.merge_asof(dota_df, market_df, on='ts_ms', direction='nearest', tolerance=2000)
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    df = df.dropna()
    
    session = ort.InferenceSession("dota_xgboost.onnx")
    input_name = session.get_inputs()[0].name
    
    signals = []
    for _, row in df.iterrows():
        input_data = np.array([[
            float(row['game_time']), float(row['nw_diff']), float(row['score_diff']),
            float(row['nw_change_60s']), float(row['score_change_60s'])
        ]], dtype=np.float32)
        
        prob_radiant = float(session.run(None, {input_name: input_data})[1][0][1])
        mid = float(row['mid'])
        edge = prob_radiant - mid
        
        # Using 4% to 9% edge filter
        if 0.04 < edge <= 0.09 and float(row['spread']) < 0.04:
            signals.append({'ts_ms': row['ts_ms'], 'match_key': row['match_key'], 'target_entry': mid})
            
    sig_df = pd.DataFrame(signals)
    
    market_df_sorted = market_df.sort_values('ts_ms')
    scalp_results = []
    
    for _, sig in sig_df.iterrows():
        entry_time = sig['ts_ms']
        max_time = entry_time + (300 * 1000)
        future_ticks = market_df_sorted[(market_df_sorted['ts_ms'] > entry_time) & (market_df_sorted['ts_ms'] <= max_time)]
        
        for _, tick in future_ticks.iterrows():
            if float(tick['mid']) - sig['target_entry'] >= 0.02:
                scalp_results.append((tick['ts_ms'] - entry_time) / 1000.0)
                break
                
    conn.close()
    
    res = pd.Series(scalp_results)
    print(f"Total Take-Profit Hits (2% move): {len(res)}")
    print(f"Mean Time to Reprice: {res.mean():.1f} seconds")
    print(f"Median Time to Reprice: {res.median():.1f} seconds")
    print(f"Fastest 25% Reprice in: {res.quantile(0.25):.1f} seconds")

if __name__ == "__main__":
    check_reprice_time()
