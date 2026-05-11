import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOTA_PATH = ROOT / "data" / "historical" / "dota_snapshots.csv"
PRICE_PATH = ROOT / "data" / "historical" / "polymarket_prices.csv"
OUT = ROOT / "data" / "historical" / "historical_events.csv"


def label_trigger(row):
    score_10 = abs(row["score_change_10s"])
    nw_10 = abs(row["nw_change_10s"])
    mkt_10 = row["market_change_10s"]

    strong = score_10 >= 2 and nw_10 >= 2000

    if strong and abs(mkt_10) < 0.01:
        return "L_STRONG_GAP"

    if strong and 0.01 <= abs(mkt_10) <= 0.05:
        return "M_STRONG_CONFIRM"

    if score_10 >= 2:
        return "FIGHT"

    if score_10 >= 1:
        return "KILL_EVENT"

    return "SLOW_BLEED"


def main():
    if not DOTA_PATH.exists() or not PRICE_PATH.exists():
        print("Input CSVs missing.")
        return

    dota = pd.read_csv(DOTA_PATH)
    px = pd.read_csv(PRICE_PATH)

    if dota.empty or px.empty:
        print("Input CSVs are empty. Fill dota_snapshots.csv and polymarket_prices.csv first.")
        return

    dota = dota.sort_values(["match_id", "ts_ms"])
    px = px.sort_values(["match_id", "ts_ms"])

    rows = []

    for match_id, d in dota.groupby("match_id"):
        p = px[px["match_id"] == match_id].copy()
        if p.empty:
            continue

        d = d.copy()
        d["score_diff"] = d["radiant_score"] - d["dire_score"]

        for _, row in d.iterrows():
            ts = row["ts_ms"]

            past = d[d["ts_ms"] <= ts - 10_000].tail(1)
            if past.empty:
                continue
            past = past.iloc[0]

            before_px = p[p["ts_ms"] <= ts].tail(1)
            px_10 = p[p["ts_ms"] <= ts - 10_000].tail(1)
            px_120 = p[p["ts_ms"] >= ts + 120_000].head(1)

            if before_px.empty or px_10.empty or px_120.empty:
                continue

            price_now = float(before_px.iloc[0]["price"])
            price_10 = float(px_10.iloc[0]["price"])
            price_120 = float(px_120.iloc[0]["price"])

            score_change_10s = float(row["score_diff"] - past["score_diff"])
            nw_change_10s = float(row["nw_diff"] - past["nw_diff"])
            market_change_10s = price_now - price_10
            market_change_120s = price_120 - price_now

            snowball = (
                abs(float(row["nw_diff"])) >= 10000
                and abs(market_change_120s) >= 0.03
                and float(row["game_time"]) >= 1200
            )

            event = {
                "match_id": match_id,
                "ts_ms": ts,
                "game_time": row["game_time"],
                "radiant_team": row["radiant_team"],
                "dire_team": row["dire_team"],
                "score_change_10s": score_change_10s,
                "nw_change_10s": nw_change_10s,
                "nw_diff": row["nw_diff"],
                "price_now": price_now,
                "market_change_10s": market_change_10s,
                "market_change_120s": market_change_120s,
                "snowball": snowball,
            }

            event["trigger"] = label_trigger(event)
            rows.append(event)

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"Wrote {OUT} with {len(out)} rows")

    if not out.empty:
        print(out.groupby(["trigger", "snowball"]).size())


if __name__ == "__main__":
    main()
