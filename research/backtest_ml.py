import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort

def backtest_ml_signals(db_path, onnx_path):
    conn = sqlite3.connect(db_path)
    
    # Fetch historical ticks where we have both dota features and market prices
    print("Loading historical live ticks for backtest...")
    dota_df = pd.read_sql_query("SELECT ts_ms, match_key, game_time, nw_diff, radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
    market_df = pd.read_sql_query("SELECT ts_ms, mid, spread, best_bid, best_ask, ask_depth FROM market_ticks WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms", conn)
    
    if dota_df.empty or market_df.empty:
        print("No paired Dota+Market ticks found in DB. Run the bot live first to collect data.")
        conn.close()
        return
        
    df = pd.merge_asof(dota_df, market_df, on='ts_ms', direction='nearest', tolerance=2000)
        
    print(f"Loaded {len(df)} paired ticks.")
    
    # Approximate 60s changes using shift (assuming ticks are roughly ~1s apart)
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    
    df = df.dropna()
    print(f"Prepared {len(df)} ticks with 60s window features.")
    
    # Load ONNX model
    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name
    
    signals = []
    
    for _, row in df.iterrows():
        input_data = np.array([[
            float(row['game_time']),
            float(row['nw_diff']),
            float(row['score_diff']),
            float(row['nw_change_60s']),
            float(row['score_change_60s'])
        ]], dtype=np.float32)
        
        pred = session.run(None, {input_name: input_data})
        prob_radiant = float(pred[1][0][1])
        
        mid = float(row['mid'])
        edge = prob_radiant - float(row['best_ask'])
        
        # Simple ML Signal threshold
        # Simulate Passive Maker Entry: Target the 'mid' price instead of aggressively crossing the spread.
        target_entry = float(row['mid'])
        edge = prob_radiant - target_entry
        if edge > 0.04 and float(row['spread']) < 0.04:
            signals.append({
                'ts_ms': row['ts_ms'],
                'match_key': row['match_key'],
                'game_time': row['game_time'],
                'prob_radiant': prob_radiant,
                'mid': mid,
                'edge': edge,
                'target_entry': target_entry,
                'action': 'BUY_RADIANT'
            })
            
    conn.close()
    
    sig_df = pd.DataFrame(signals)
    if sig_df.empty:
        print("No signals generated. Edge threshold (4%) was not met historically.")
        return
        
    print(f"\nGenerated {len(sig_df)} ML signals over historical data!")
    
    print("Simulating Scalper Execution (Take-Profit & Stop-Loss)...")
    
    # We will iterate through signals and find the first exit trigger
    tp_level = 0.02 # 2% take profit
    sl_level = -0.02 # 2% stop loss
    timeout_s = 300 # 5 minutes max hold time
    
    scalp_results = []
    
    market_df_sorted = market_df.sort_values('ts_ms')
    
    for _, sig in sig_df.iterrows():
        entry_time = sig['ts_ms']
        entry_price = sig['target_entry']
        match_key = sig['match_key']
        max_time = entry_time + (timeout_s * 1000)
        
        # Filter future market ticks for this match within the timeout window
        future_ticks = market_df_sorted[
            (market_df_sorted['ts_ms'] > entry_time) & 
            (market_df_sorted['ts_ms'] <= max_time)
        ]
        
        pnl = 0.0
        exit_time = None
        exit_reason = "TIMEOUT"
        
        for _, tick in future_ticks.iterrows():
            current_mid = float(tick['mid'])
            current_pnl = current_mid - entry_price
            
            if current_pnl >= tp_level:
                pnl = tp_level
                exit_time = tick['ts_ms']
                exit_reason = "TAKE_PROFIT"
                break
            elif current_pnl <= sl_level:
                pnl = sl_level
                exit_time = tick['ts_ms']
                exit_reason = "STOP_LOSS"
                break
                
        if exit_reason == "TIMEOUT":
            # Exit at market at the end of the window if neither hit
            if not future_ticks.empty:
                final_mid = float(future_ticks.iloc[-1]['mid'])
                pnl = final_mid - entry_price
            else:
                pnl = 0.0
                
        scalp_results.append({
            'pnl': pnl,
            'exit_reason': exit_reason,
            'hold_time_s': ((exit_time or max_time) - entry_time) / 1000
        })
        
    res_df = pd.DataFrame(scalp_results)
    sig_df = pd.concat([sig_df.reset_index(drop=True), res_df], axis=1)

    print("\nSample Scalp Trades:")
    cols_to_show = ['game_time', 'edge', 'target_entry', 'pnl', 'exit_reason', 'hold_time_s']
    print(sig_df[cols_to_show].head(15).to_string(index=False))
    
    print("\n--- Scalper Backtest Performance Summary ---")
    print(f"Total Signals: {len(sig_df)}")
    print(f"Mean PnL:   {sig_df['pnl'].mean():.4f}")
    print(f"Win Rate:   {(sig_df['pnl'] > 0).mean():.2%}")
    
    print("\nExit Reasons:")
    print(sig_df['exit_reason'].value_counts())
    
    sig_df['edge_bucket'] = pd.cut(sig_df['edge'], bins=[0.04, 0.06, 0.08, 0.10, 1.0], labels=["4-6%", "6-8%", "8-10%", "10%+"])
    print("\nBy Edge Bucket:")
    print(sig_df.groupby('edge_bucket', observed=False).agg(
        signals=('ts_ms', 'count'),
        win_rate=('pnl', lambda x: (x > 0).mean()),
        mean_pnl=('pnl', 'mean')
    ))

if __name__ == "__main__":
    db = "../data/dota_poly_collection.sqlite"
    onnx = "dota_xgboost.onnx"
    backtest_ml_signals(db, onnx)
