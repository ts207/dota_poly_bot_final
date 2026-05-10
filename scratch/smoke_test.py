import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force lower env thresholds for the smoke test
os.environ["SIGNAL_MIN_EDGE"] = "0.04"
os.environ["SIGNAL_MIN_EXPECTED_MOVE"] = "0.02"

from core.signals import SignalEngine, Trigger, BLOCKED_TRIGGERS, TRIGGER_EDGE_FLOORS
e = SignalEngine()
print("Import OK")
print("Blocked triggers:", BLOCKED_TRIGGERS)
print("ONNX model loaded:", e.ort_session is not None)

# FIGHT scenario: big NW swing + kills → should generate a signal
fight_features = {
    "match_key": "test_fight",
    "game_time": 900.0,       # 15 min
    "nw_diff": 8000.0,
    "score_diff": 5.0,
    "nw_change_60s": 2500.0,  # big NW swing
    "score_change_60s": 3.0,  # kills happened
    "mid": 0.82,   # ML prob ~0.875 → edge ~5.5% → within 4-9% window
    "spread": 0.02,
    "combined_mid_disagreement": 0.01,
    "building_change_60s": 0,
    "market_change_60s": 0.0,
}
print("\n[FIGHT trigger — expected: BUY_RADIANT_YES signal]")
print(e.generate(fight_features))

# ECONOMIC SWING — should be blocked
eco_features = dict(fight_features, match_key="test_eco", score_change_60s=0.0)
print("\n[ECONOMIC SWING — expected: None (blocked)]")
print(e.generate(eco_features))

# Dedup — same match/minute should be silent
print("\n[DEDUP — same match+minute as fight, expected: None]")
print(e.generate(dict(fight_features)))  # same match_key + same game_minute

