import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["SIGNAL_MIN_EDGE"] = "0.01"
os.environ["SIGNAL_MIN_EXPECTED_MOVE"] = "0.01"

from core.signals import SignalEngine
e = SignalEngine()

f = {
    "match_key": "t", "game_time": 900, "nw_diff": 8000, "score_diff": 5,
    "nw_change_60s": 2500, "score_change_60s": 3, "mid": 0.87,
    "spread": 0.02, "combined_mid_disagreement": 0.01,
    "building_change_60s": 0, "market_change_60s": 0
}
print("trigger:", e.classify(f))
print("prob:", round(e.predict_win_prob(f), 4))
print("edge would be:", round(e.predict_win_prob(f) - f["mid"], 4))
print("signal:", e.generate(f))

# second test — different minute, mid=0.86
f2 = dict(f, match_key="t2", mid=0.86)
print("\n--- Second test (mid=0.86, different match) ---")
print("edge:", round(e.predict_win_prob(f2) - f2["mid"], 4))
print("signal:", e.generate(f2))
