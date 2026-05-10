import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["SIGNAL_MIN_EDGE"] = "0.01"
os.environ["SIGNAL_MIN_EXPECTED_MOVE"] = "0.01"

from core.signals import SignalEngine
e = SignalEngine()

# Scenario A: ask at mid — zero real edge even if predicted move is large
f_tight = {
    "match_key": "tight", "game_time": 900, "nw_diff": 8000, "score_diff": 5,
    "nw_change_60s": 2500, "score_change_60s": 3,
    "mid": 0.87, "spread": 0.02, "combined_mid_disagreement": 0.01,
    "building_change_60s": 0, "market_change_60s": 0,
    "radiant_best_ask": 0.945,   # ask already at fair value → real edge ≈ 0
    "best_ask": 0.945,
}
prob = e.predict_win_prob(f_tight)
fair = min(0.99, f_tight["mid"] + (prob - f_tight["mid"]))
print(f"Scenario A — ask at fair value")
print(f"  ML prob: {prob:.4f}  fair: {fair:.4f}  ask: {f_tight['radiant_best_ask']}")
print(f"  Real edge: {fair - f_tight['radiant_best_ask']:.4f}  (expected: near 0)")
print(f"  Signal: {e.generate(f_tight)}\n")

# Scenario B: ask lagging — clear executable edge
f_lag = dict(f_tight, match_key="lag", radiant_best_ask=0.87, best_ask=0.87)
prob2 = e.predict_win_prob(f_lag)
fair2 = min(0.99, f_lag["mid"] + (prob2 - f_lag["mid"]))
print(f"Scenario B — ask lagging at mid")
print(f"  ML prob: {prob2:.4f}  fair: {fair2:.4f}  ask: {f_lag['radiant_best_ask']}")
print(f"  Real edge: {fair2 - f_lag['radiant_best_ask']:.4f}  (expected: ~7.5%)")
print(f"  Signal: {e.generate(f_lag)}")
