import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import requests

slug = "dota2-rnx-ngx-2026-05-10-game1"
resp = requests.get(f"https://gamma-api.polymarket.com/markets?slug={slug}")
data = resp.json()
if data:
    m = data[0]
    print(f"Market: {m['question']}")
    print(f"Condition ID: {m['conditionId']}")
    print(f"Outcomes: {m['outcomes']}")
    print(f"Tokens: {m['clobTokenIds']}")
else:
    print("Market not found.")
