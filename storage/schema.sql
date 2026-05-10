CREATE TABLE IF NOT EXISTS dota_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    match_key TEXT,
    server_steam_id TEXT,
    partner INTEGER,
    radiant_team TEXT,
    dire_team TEXT,
    game_time REAL,
    radiant_score INTEGER,
    dire_score INTEGER,
    radiant_nw REAL,
    dire_nw REAL,
    nw_diff REAL,
    total_nw REAL,
    nw_diff_pct REAL
);

CREATE INDEX IF NOT EXISTS idx_dota_ticks_ts ON dota_ticks(ts_ms);
CREATE INDEX IF NOT EXISTS idx_dota_ticks_match ON dota_ticks(match_key, ts_ms);

CREATE TABLE IF NOT EXISTS market_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    market_id TEXT,
    token_id TEXT,
    best_bid REAL,
    best_ask REAL,
    mid REAL,
    spread REAL,
    bid_depth REAL,
    ask_depth REAL
);

CREATE INDEX IF NOT EXISTS idx_market_ticks_ts ON market_ticks(ts_ms);
CREATE INDEX IF NOT EXISTS idx_market_ticks_market_token_ts ON market_ticks(market_id, token_id, ts_ms);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    match_key TEXT,
    market_id TEXT,
    target_token_id TEXT,
    side TEXT,
    signal_type TEXT,
    trigger TEXT,
    fair_price REAL,
    game_time REAL,
    nw_change_10s REAL DEFAULT 0,
    nw_change_30s REAL DEFAULT 0,
    nw_change_60s REAL DEFAULT 0,
    score_change_10s INTEGER DEFAULT 0,
    score_change_30s INTEGER DEFAULT 0,
    score_change_60s INTEGER DEFAULT 0,
    market_change_10s REAL DEFAULT 0,
    market_change_30s REAL DEFAULT 0,
    market_change_60s REAL DEFAULT 0,
    expected_move REAL,
    market_lag REAL,
    edge REAL,
    combined_mid_disagreement REAL DEFAULT 0,
    action TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts_ms);
CREATE INDEX IF NOT EXISTS idx_signals_market_ts ON signals(market_id, ts_ms);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    market_id TEXT,
    token_id TEXT,
    side TEXT,
    price REAL,
    size REAL,
    status TEXT,
    signal_id INTEGER,
    ack_ms INTEGER,
    fill_price REAL,
    filled_size REAL
);

CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts_ms);
CREATE INDEX IF NOT EXISTS idx_orders_signal_id ON orders(signal_id);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    order_id INTEGER,
    ts_ms INTEGER NOT NULL,
    market_id TEXT,
    token_id TEXT,
    side TEXT,
    intended_price REAL,
    intended_size REAL,
    filled INTEGER DEFAULT 0,
    fill_price REAL,
    fill_ts_ms INTEGER,
    exit_bid_15s REAL,
    exit_bid_30s REAL,
    exit_bid_60s REAL,
    exit_bid_120s REAL,
    pnl_15s REAL,
    pnl_30s REAL,
    pnl_60s REAL,
    pnl_120s REAL
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_signal ON paper_trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ts ON paper_trades(ts_ms);
