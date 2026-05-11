import sqlite3, pandas as pd
conn = sqlite3.connect('data/1win_pari_g3.sqlite')

print('=== G3 RUN CONFIGS ===')
rc = pd.read_sql("SELECT * FROM run_configs", conn)
print(rc[['run_id','ts_ms','enabled_triggers','blocked_triggers','signal_min_edge','risk_max_book_age_ms']].to_string())

print()
print('=== G3 DOTA TICKS SAMPLE ===')
t = pd.read_sql("SELECT * FROM dota_ticks ORDER BY ts_ms LIMIT 5", conn)
print(t.columns.tolist())
print(t.to_string())

print()
print('=== G3 MARKET TICKS sample ===')
mt = pd.read_sql("SELECT * FROM market_ticks ORDER BY ts_ms LIMIT 5", conn)
print(mt.columns.tolist())
print(mt.to_string())

print()
print('=== DOTA TICK FEATURE COVERAGE ===')
dt = pd.read_sql("SELECT * FROM dota_ticks ORDER BY ts_ms LIMIT 20", conn)
print(dt[['game_time','nw_diff','ts_ms']].to_string())

print()
print('=== MATCH COVERAGE ===')
cov = pd.read_sql(
    "SELECT match_key, run_id, COUNT(*) as n, MIN(game_time) as gt_min, MAX(game_time) as gt_max "
    "FROM dota_ticks GROUP BY match_key, run_id ORDER BY MIN(ts_ms)", conn)
print(cov.to_string())

print()
print('=== G3 SHADOW SIGNALS CSV ===')
try:
    with open('data/shadow_signals_g3.csv') as f:
        print(f.read())
except Exception as e:
    print(f'Error: {e}')

conn.close()

print()
print('=== SHADOW SIGNALS MAIN CSV (parse error) ===')
with open('data/shadow_signals.csv') as f:
    lines = f.readlines()
print(f'Total lines: {len(lines)}')
print('Header:', repr(lines[0][:300]))
print('Line 33:', repr(lines[32][:300]))
print('Line 34:', repr(lines[33][:300]))
print('Line 35:', repr(lines[34][:300] if len(lines) > 34 else 'EOF'))
print()
print('Field count per line:')
header_fields = len(lines[0].split(','))
print(f'  Header has {header_fields} fields')
for i, l in enumerate(lines[1:], 1):
    n = len(l.split(','))
    if n != header_fields:
        print(f'  Line {i+1}: {n} fields (MISMATCH) -> {repr(l[:200])}')
