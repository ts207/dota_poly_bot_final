"""
Latency Edge Analysis
Measures the time delta between a Steam poll state change and the
corresponding Polymarket price correction for each scalp trade.
"""
import sqlite3
import pandas as pd
import numpy as np
import onnxruntime as ort

def analyze_latency():
    conn = sqlite3.connect("./data/dota_poly_collection.sqlite")
    dota_df = pd.read_sql_query(
        "SELECT ts_ms, match_key, game_time, nw_diff, radiant_score, dire_score, "
        "radiant_score - dire_score AS score_diff FROM dota_ticks ORDER BY ts_ms", conn)
    market_df = pd.read_sql_query(
        "SELECT ts_ms, mid, spread FROM market_ticks "
        "WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms", conn)

    df = pd.merge_asof(dota_df, market_df, on='ts_ms', direction='nearest', tolerance=2000)
    df['nw_change_60s'] = df.groupby('match_key')['nw_diff'].diff(periods=60).fillna(0)
    df['score_change_60s'] = df.groupby('match_key')['score_diff'].diff(periods=60).fillna(0)
    df['game_minute'] = (df['game_time'] // 60).astype(int)
    df = df.dropna()

    session = ort.InferenceSession("./research/dota_xgboost.onnx")
    input_name = session.get_inputs()[0].name

    signals = []
    for _, row in df.iterrows():
        inp = np.array([[float(row['game_time']), float(row['nw_diff']),
                         float(row['score_diff']), float(row['nw_change_60s']),
                         float(row['score_change_60s'])]], dtype=np.float32)
        prob = float(session.run(None, {input_name: inp})[1][0][1])
        mid = float(row['mid'])
        edge = prob - mid
        if abs(edge) > 0.02 and float(row['spread']) < 0.15:
            signals.append({
                'ts_ms': row['ts_ms'],
                'match_key': row['match_key'],
                'game_time': row['game_time'],
                'game_minute': row['game_minute'],
                'nw_change_60s': row['nw_change_60s'],
                'score_change_60s': row['score_change_60s'],
                'ml_prob': prob,
                'entry_mid': mid,
                'edge': edge
            })

    if not signals:
        print("No signals found with current thresholds.")
        return

    sig_df = pd.DataFrame(signals)
    sig_df = sig_df.sort_values('ts_ms').drop_duplicates(
        subset=['match_key', 'game_minute'], keep='first').reset_index(drop=True)

    print(f"Analyzing {len(sig_df)} deduped signals...\n")

    market_sorted = market_df.sort_values('ts_ms')
    records = []

    for _, sig in sig_df.iterrows():
        entry_ts   = sig['ts_ms']
        entry_mid  = sig['entry_mid']
        tp_target  = entry_mid + 0.02
        sl_target  = entry_mid - 0.02
        window     = market_sorted[(market_sorted['ts_ms'] > entry_ts) &
                                   (market_sorted['ts_ms'] <= entry_ts + 300_000)]

        reprice_s    = None
        sl_s         = None
        final_pnl    = None
        exit_reason  = "TIMEOUT"

        for _, tick in window.iterrows():
            cur = float(tick['mid'])
            elapsed = (tick['ts_ms'] - entry_ts) / 1000.0
            if cur >= tp_target:
                reprice_s   = elapsed
                final_pnl   = 0.02
                exit_reason = "TAKE_PROFIT"
                break
            elif cur <= sl_target:
                sl_s        = elapsed
                final_pnl   = -0.02
                exit_reason = "STOP_LOSS"
                break

        if exit_reason == "TIMEOUT" and not window.empty:
            final_pnl = float(window.iloc[-1]['mid']) - entry_mid

        # Trigger classification
        big_nw_swing  = abs(sig['nw_change_60s']) >= 2000
        kill_event    = abs(sig['score_change_60s']) >= 2

        if kill_event and big_nw_swing:
            trigger = "FIGHT (kills + NW)"
        elif kill_event:
            trigger = "KILL EVENT"
        elif big_nw_swing:
            trigger = "ECONOMIC SWING"
        else:
            trigger = "SLOW BLEED"

        records.append({
            'match_key':   sig['match_key'],
            'game_time_m': round(sig['game_time'] / 60, 1),
            'trigger':     trigger,
            'nw_swing':    round(sig['nw_change_60s']),
            'kill_swing':  round(sig['score_change_60s']),
            'ml_prob':     round(sig['ml_prob'], 3),
            'entry_mid':   round(entry_mid, 3),
            'edge':        round(sig['edge'], 3),
            'reprice_s':   reprice_s,
            'exit_reason': exit_reason,
            'pnl':         round(final_pnl, 4) if final_pnl is not None else None
        })

    res = pd.DataFrame(records)

    print("=" * 65)
    print("LATENCY EDGE ANALYSIS — ALL DEDUPED TRADES")
    print("=" * 65)
    print(res[['game_time_m','trigger','edge','entry_mid','reprice_s','exit_reason','pnl']].to_string(index=False))

    print("\n" + "=" * 65)
    print("PERFORMANCE BY TRIGGER TYPE")
    print("=" * 65)
    grp = res.groupby('trigger').agg(
        trades=('pnl', 'count'),
        tp_rate=('exit_reason', lambda x: (x == 'TAKE_PROFIT').mean()),
        sl_rate=('exit_reason', lambda x: (x == 'STOP_LOSS').mean()),
        mean_reprice_s=('reprice_s', lambda x: x.dropna().mean()),
        mean_pnl=('pnl', 'mean')
    ).round(3)
    print(grp.to_string())

    print("\n" + "=" * 65)
    print("LATENCY DISTRIBUTION (Take-Profit trades only)")
    print("=" * 65)
    tp = res[res['exit_reason'] == 'TAKE_PROFIT']['reprice_s'].dropna()
    if not tp.empty:
        print(f"  Count:       {len(tp)}")
        print(f"  Min:         {tp.min():.1f}s")
        print(f"  25th pct:    {tp.quantile(0.25):.1f}s")
        print(f"  Median:      {tp.median():.1f}s")
        print(f"  75th pct:    {tp.quantile(0.75):.1f}s")
        print(f"  Max:         {tp.max():.1f}s")
        print(f"  Mean:        {tp.mean():.1f}s")

    conn.close()

if __name__ == "__main__":
    analyze_latency()
