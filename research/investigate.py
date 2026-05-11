import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort

def investigate_anomalies(db_path, onnx_path):
    conn = sqlite3.connect(db_path)
    
    print("Loading historical ticks for anomaly investigation...")
    dota_df = pd.read_sql_query("SELECT ts_ms, match_key, game_time, nw_diff, radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
    market_df = pd.read_sql_query("SELECT ts_ms, mid, spread FROM market_ticks WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms", conn)
    
    df = pd.merge_asof(dota_df, market_df, on='ts_ms', direction='nearest', tolerance=2000)
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    df = df.dropna()
    
    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name
    
    signals = []
    for _, row in df.iterrows():
        input_data = np.array([[
            float(row['game_time']), float(row['nw_diff']), float(row['score_diff']),
            float(row['nw_change_60s']), float(row['score_change_60s'])
        ]], dtype=np.float32)
        
        pred = session.run(None, {input_name: input_data})
        prob_radiant = float(pred[1][0][1])
        mid = float(row['mid'])
        edge = prob_radiant - mid
        
        if edge >= 0.10 and float(row['spread']) < 0.04:
            signals.append({
                'ts_ms': row['ts_ms'],
                'match_key': row['match_key'],
                'game_time': row['game_time'],
                'nw_diff': row['nw_diff'],
                'prob_radiant': prob_radiant,
                'mid': mid,
                'edge': edge
            })
            
    conn.close()
    
    sig_df = pd.DataFrame(signals)
    if sig_df.empty:
        print("No 10%+ edge signals found.")
        return
        
    print(f"Found {len(sig_df)} Extreme Signals (Edge >= 10%)")
    
    print("\nBreakdown by Match:")
    print(sig_df.groupby('match_key').size())
    
    print("\nMean Game Time by Match for Extreme Signals:")
    print(sig_df.groupby('match_key')['game_time'].mean())
    
    print("\nSample of Extreme Signals:")
    print(sig_df[['match_key', 'game_time', 'nw_diff', 'prob_radiant', 'mid', 'edge']].head(20).to_string(index=False))

if __name__ == "__main__":
    investigate_anomalies("./data/dota_poly_collection.sqlite", "./research/dota_xgboost.onnx")
