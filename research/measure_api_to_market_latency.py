import sqlite3
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "dota_poly_collection.sqlite"

EVENT_NW_THRESHOLD = 500      # raw radiant_lead move
EVENT_SCORE_THRESHOLD = 1     # kill score change
MARKET_MOVE_THRESHOLD = 0.01  # 1 cent market move
LOOKAHEAD_SECONDS = 30


def main():
    conn = sqlite3.connect(DB)

    dota = pd.read_sql_query(
        """
        SELECT ts_ms, match_key, game_time, nw_diff, radiant_score, dire_score
        FROM dota_ticks
        ORDER BY ts_ms ASC
        """,
        conn,
    )

    market = pd.read_sql_query(
        """
        SELECT ts_ms, token_id, mid, best_bid, best_ask
        FROM market_ticks
        WHERE token_id = 'COMBINED_RADIANT'
        ORDER BY ts_ms ASC
        """,
        conn,
    )

    conn.close()

    if dota.empty or market.empty:
        print("Missing dota_ticks or COMBINED_RADIANT market_ticks.")
        return

    dota["score_diff"] = dota["radiant_score"] - dota["dire_score"]
    dota["nw_change"] = dota["nw_diff"].diff()
    dota["score_change"] = dota["score_diff"].diff()

    events = dota[
        (dota["nw_change"].abs() >= EVENT_NW_THRESHOLD)
        | (dota["score_change"].abs() >= EVENT_SCORE_THRESHOLD)
    ].copy()

    results = []

    for _, e in events.iterrows():
        event_ts = int(e["ts_ms"])
        before = market[market["ts_ms"] <= event_ts].tail(1)

        if before.empty:
            continue

        base_mid = float(before.iloc[0]["mid"])

        future = market[
            (market["ts_ms"] > event_ts)
            & (market["ts_ms"] <= event_ts + LOOKAHEAD_SECONDS * 1000)
        ].copy()

        if future.empty:
            continue

        future["market_move"] = future["mid"] - base_mid
        moved = future[future["market_move"].abs() >= MARKET_MOVE_THRESHOLD]

        if moved.empty:
            continue

        first = moved.iloc[0]
        latency_s = (int(first["ts_ms"]) - event_ts) / 1000.0

        results.append(
            {
                "event_time_s": e["game_time"],
                "event_minute": e["game_time"] / 60.0,
                "event_ts_ms": event_ts,
                "nw_change": e["nw_change"],
                "score_change": e["score_change"],
                "base_mid": base_mid,
                "first_market_mid": first["mid"],
                "market_move": first["market_move"],
                "latency_s": latency_s,
            }
        )

    out = pd.DataFrame(results)

    if out.empty:
        print("No API-to-market repricing events found.")
        return

    print("\n=== API → Polymarket Latency ===")
    print(f"Events measured: {len(out)}")
    print(f"Median latency: {out['latency_s'].median():.2f}s")
    print(f"Mean latency:   {out['latency_s'].mean():.2f}s")
    print(f"p25 latency:    {out['latency_s'].quantile(0.25):.2f}s")
    print(f"p75 latency:    {out['latency_s'].quantile(0.75):.2f}s")

    print("\nLatency buckets:")
    print(
        pd.cut(
            out["latency_s"],
            bins=[0, 2, 5, 10, 20, 30],
            labels=["0-2s", "2-5s", "5-10s", "10-20s", "20-30s"],
        )
        .value_counts()
        .sort_index()
    )

    print("\nBy event type:")
    out["event_type"] = "NW"
    out.loc[out["score_change"].abs() >= EVENT_SCORE_THRESHOLD, "event_type"] = "KILL"
    out.loc[
        (out["score_change"].abs() >= EVENT_SCORE_THRESHOLD)
        & (out["nw_change"].abs() >= EVENT_NW_THRESHOLD),
        "event_type",
    ] = "KILL+NW"

    print(
        out.groupby("event_type")
        .agg(
            events=("latency_s", "count"),
            median_latency=("latency_s", "median"),
            mean_latency=("latency_s", "mean"),
            mean_market_move=("market_move", "mean"),
        )
        .round(4)
    )

    out_path = ROOT / "data" / "api_to_market_latency.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
