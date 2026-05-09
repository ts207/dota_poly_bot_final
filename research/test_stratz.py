import requests
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
token = os.getenv("STRATZ_API_KEY")

query = """
{
  player(steamAccountId: 1596698187) {
    matches(request: { take: 1, isParsed: true }) {
      id
      didRadiantWin
      players {
        isRadiant
        playbackData {
          killEvents {
            time
          }
        }
      }
    }
  }
}
"""

url = "https://api.stratz.com/graphql"
headers = {"Authorization": f"Bearer {token}", "User-Agent": "STRATZ_API"}
r = requests.post(url, json={"query": query}, headers=headers)
print(r.status_code)
if r.status_code == 200:
    print(json.dumps(r.json(), indent=2)[:500])
else:
    print(r.text)

