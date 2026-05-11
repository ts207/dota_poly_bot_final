import json
import sys
from pathlib import Path

TIME_KEYS = {
    "timestamp", "ts", "time", "server_time", "created_at", "updated_at",
    "started_at", "start_time", "match_time", "game_time", "duration",
}

DATA_KEYS = {
    "networth", "net_worth", "nw", "gold", "score", "radiant_score",
    "dire_score", "radiant_networth", "dire_networth", "networth_diff",
}


def walk(obj, path=""):
    if isinstance(obj, dict):
        keys = set(obj.keys())
        hit_time = keys & TIME_KEYS
        hit_data = keys & DATA_KEYS

        if hit_time or hit_data:
            print("\nPATH:", path or "$")
            print("TIME KEYS:", sorted(hit_time))
            print("DATA KEYS:", sorted(hit_data))
            preview = {k: obj.get(k) for k in list(hit_time | hit_data)[:20]}
            print("PREVIEW:", preview)

        for k, v in obj.items():
            walk(v, f"{path}.{k}" if path else k)

    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            walk(v, f"{path}[{i}]")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 research/historical/inspect_dltv_json.py file.json")
        return

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())
    walk(data)


if __name__ == "__main__":
    main()
