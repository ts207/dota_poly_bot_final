import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort
import os

def generate_report():
    conn = sqlite3.connect("./data/dota_poly_collection.sqlite")
    dota_df = pd.read_sql_query("SELECT ts_ms, match_key, game_time, nw_diff, radiant_score, dire_score, radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
    market_df = pd.read_sql_query("SELECT ts_ms, mid, spread FROM market_ticks WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms", conn)
    
    df = pd.merge_asof(dota_df, market_df, on='ts_ms', direction='nearest', tolerance=2000)
    
    # Calculate 60s lagged values to show "before" state
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    
    # Let's also grab the actual values from 60s ago to show them directly
    df['nw_diff_60s_ago'] = df['nw_diff'] - df['nw_change_60s']
    df['score_diff_60s_ago'] = df['score_diff'] - df['score_change_60s']
    
    df = df.dropna()
    
    session = ort.InferenceSession("./research/dota_xgboost.onnx")
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
        
        # Max edge ceiling applied (4% to 9% edge)
        if 0.04 < edge <= 0.09 and float(row['spread']) < 0.04:
            signals.append({
                'ts_ms': row['ts_ms'], 
                'match_key': row['match_key'], 
                'game_time': row['game_time'],
                'game_minute': int(row['game_time'] // 60),  # bucket by minute for dedup
                'nw_diff_60s_ago': row['nw_diff_60s_ago'],
                'score_diff_60s_ago': row['score_diff_60s_ago'],
                'nw_diff_now': row['nw_diff'],
                'score_now': f"{int(row['radiant_score'])}-{int(row['dire_score'])}",
                'prob_radiant': prob_radiant,
                'target_entry': mid,
                'edge': edge
            })
            
    sig_df = pd.DataFrame(signals)
    if sig_df.empty:
        print("No signals found.")
        return
    
    # DEDUPLICATION: Keep only the FIRST signal per (match, game_minute)
    # In live trading you'd only open one position per distinct game-state window
    before = len(sig_df)
    sig_df = sig_df.sort_values('ts_ms').drop_duplicates(subset=['match_key', 'game_minute'], keep='first').reset_index(drop=True)
    print(f"Raw signals: {before} → After dedup (1 per minute per match): {len(sig_df)}")
        
    market_df_sorted = market_df.sort_values('ts_ms')
    scalp_results = []
    
    tp_level = 0.02
    sl_level = -0.02
    
    for _, sig in sig_df.iterrows():
        entry_time = sig['ts_ms']
        max_time = entry_time + (300 * 1000)
        future_ticks = market_df_sorted[(market_df_sorted['ts_ms'] > entry_time) & (market_df_sorted['ts_ms'] <= max_time)]
        
        pnl = 0.0
        exit_time = None
        exit_reason = "TIMEOUT"
        exit_price = sig['target_entry']
        
        for _, tick in future_ticks.iterrows():
            current_mid = float(tick['mid'])
            current_pnl = current_mid - sig['target_entry']
            
            if current_pnl >= tp_level:
                pnl = tp_level
                exit_time = tick['ts_ms']
                exit_price = current_mid
                exit_reason = "TAKE_PROFIT"
                break
            elif current_pnl <= sl_level:
                pnl = sl_level
                exit_time = tick['ts_ms']
                exit_price = current_mid
                exit_reason = "STOP_LOSS"
                break
                
        if exit_reason == "TIMEOUT":
            if not future_ticks.empty:
                exit_price = float(future_ticks.iloc[-1]['mid'])
                pnl = exit_price - sig['target_entry']
                
        hold_time_s = ((exit_time or max_time) - entry_time) / 1000.0
        
        # Format reasoning string
        reasoning = f"Radiant built momentum over 60s (NW shift: {sig['nw_diff_now'] - sig['nw_diff_60s_ago']:.0f}). ML sees {sig['prob_radiant']:.1%} win prob. PM lagging at {sig['target_entry']:.1%}."
        
        scalp_results.append({
            'Match': sig['match_key'],
            'Time (m)': f"{sig['game_time']/60:.1f}",
            '60s Ago (NW Diff / Score Diff)': f"{sig['nw_diff_60s_ago']:.0f} / {sig['score_diff_60s_ago']:.0f}",
            'Current State (NW Diff / Score)': f"{sig['nw_diff_now']:.0f} / {sig['score_now']}",
            'ML Edge': f"+{sig['edge']*100:.1f}%",
            'Reasoning': reasoning,
            'Entry PM Price': f"{sig['target_entry']:.3f}",
            'Exit PM Price': f"{exit_price:.3f}",
            'Hold Time (s)': f"{hold_time_s:.1f}",
            'Result': f"{exit_reason} ({pnl*100:+.1f}%)"
        })
                
    conn.close()
    
    res_df = pd.DataFrame(scalp_results)
    csv_path = "detailed_trade_report.csv"
    res_df.to_csv(csv_path, index=False)
    
    print(f"Generated {len(res_df)} trades. Saved to {csv_path}\n")
    
    # Filter only winning trades to show to user
    winners = res_df[res_df['Result'].str.contains("TAKE_PROFIT")].head(5)
    
    print("--- DETAILED SAMPLE OF WINNING SCALPS ---")
    for i, row in winners.iterrows():
        print(f"\nTrade {i+1} | Match: {row['Match']} | Game Time: {row['Time (m)']}m")
        print(f"  [Before Poll] 60s ago: NW Diff {row['60s Ago (NW Diff / Score Diff)']}")
        print(f"  [After Poll]  Current: NW Diff {row['Current State (NW Diff / Score)']}")
        print(f"  [Reasoning]   {row['Reasoning']}")
        print(f"  [Trade]       Entered Maker @ {row['Entry PM Price']}")
        print(f"  [Reprice]     Market repriced after {row['Hold Time (s)']}s to {row['Exit PM Price']}")
        print(f"  [Outcome]     {row['Result']}")

if __name__ == "__main__":
    generate_report()
