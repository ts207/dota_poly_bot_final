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
    trigger_strength TEXT,
    trigger_window TEXT,
    market_state TEXT,
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

CREATE TABLE IF NOT EXISTS live_order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    signal_id INTEGER,
    market_id TEXT,
    token_id TEXT,
    exchange_order_id TEXT,
    event_type TEXT,
    intended_price REAL,
    intended_size REAL,
    filled_size REAL,
    avg_fill_price REAL,
    remaining_size REAL,
    ack_ms INTEGER,
    fill_ts_ms INTEGER,
    raw_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_live_order_events_order ON live_order_events(exchange_order_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_live_order_events_signal ON live_order_events(signal_id, ts_ms);

CREATE TABLE IF NOT EXISTS live_fill_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    exchange_order_id TEXT,
    signal_id INTEGER,
    market_id TEXT,
    token_id TEXT,
    seconds_after_fill REAL,
    best_bid REAL,
    best_ask REAL,
    mid REAL,
    spread REAL,
    bid_depth REAL,
    ask_depth REAL
);

CREATE INDEX IF NOT EXISTS idx_live_fill_snapshots_order ON live_fill_snapshots(exchange_order_id, seconds_after_fill);


CREATE TABLE IF NOT EXISTS signal_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    match_key TEXT,
    market_id TEXT,
    token_id TEXT,
    trigger TEXT,
    trigger_strength TEXT,
    side TEXT,
    reason TEXT,
    game_time REAL,
    mid REAL,
    spread REAL,
    combined_mid_disagreement REAL,
    expected_move REAL,
    fair_price REAL,
    edge REAL,
    edge_floor REAL
);

CREATE INDEX IF NOT EXISTS idx_signal_rejections_reason ON signal_rejections(reason, trigger, ts_ms);
CREATE INDEX IF NOT EXISTS idx_signal_rejections_market ON signal_rejections(market_id, ts_ms);
