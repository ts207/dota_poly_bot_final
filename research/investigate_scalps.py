import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort

def investigate_trades():
    conn = sqlite3.connect("../data/dota_poly_collection.sqlite")
    dota_df = pd.read_sql_query("SELECT ts_ms, match_key, game_time, nw_diff, radiant_score, dire_score, radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
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
            signals.append({
                'ts_ms': row['ts_ms'], 
                'match_key': row['match_key'], 
                'game_time': row['game_time'],
                'nw_diff': row['nw_diff'],
                'radiant_score': row['radiant_score'],
                'dire_score': row['dire_score'],
                'prob_radiant': prob_radiant,
                'target_entry': mid
            })
            
    sig_df = pd.DataFrame(signals)
    
    market_df_sorted = market_df.sort_values('ts_ms')
    scalp_results = []
    
    for _, sig in sig_df.iterrows():
        entry_time = sig['ts_ms']
        max_time = entry_time + (300 * 1000)
        future_ticks = market_df_sorted[(market_df_sorted['ts_ms'] > entry_time) & (market_df_sorted['ts_ms'] <= max_time)]
        
        for _, tick in future_ticks.iterrows():
            if float(tick['mid']) - sig['target_entry'] >= 0.02:
                scalp_results.append({
                    'match_key': sig['match_key'],
                    'game_time': sig['game_time'],
                    'nw_diff': sig['nw_diff'],
                    'score': f"{int(sig['radiant_score'])}-{int(sig['dire_score'])}",
                    'ml_prob': sig['prob_radiant'],
                    'entry_price': sig['target_entry'],
                    'exit_price': float(tick['mid']),
                    'hold_time_s': (tick['ts_ms'] - entry_time) / 1000.0
                })
                break
                
    conn.close()
    
    res = pd.DataFrame(scalp_results)
    
    print("--- 5 SAMPLE FAST SCALPS (< 20 seconds) ---")
    fast_scalps = res[res['hold_time_s'] < 20].head(5)
    print(fast_scalps.to_string(index=False))
    
    print("\n--- 5 SAMPLE MEDIAN SCALPS (~60 seconds) ---")
    median_scalps = res[(res['hold_time_s'] > 50) & (res['hold_time_s'] < 70)].head(5)
    print(median_scalps.to_string(index=False))

if __name__ == "__main__":
    investigate_trades()
