import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "historical" / "historical_events.csv"

MAKER_EXIT_HAIRCUT = 0.01
TAKER_ENTRY_HAIRCUT = 0.02


def main():
    if not EVENTS.exists():
        print("Run build_historical_events.py first.")
        return

    df = pd.read_csv(EVENTS)

    if df.empty:
        print("historical_events.csv is empty.")
        return

    enabled = df[df["trigger"].isin([
        "L_STRONG_GAP",
        "M_STRONG_CONFIRM",
        "FIGHT",
        "SLOW_BLEED",
        "KILL_EVENT",
    ])].copy()

    enabled["maker_pnl_120s"] = enabled["market_change_120s"] - MAKER_EXIT_HAIRCUT
    enabled["taker_pnl_120s"] = (
        enabled["market_change_120s"]
        - TAKER_ENTRY_HAIRCUT
        - MAKER_EXIT_HAIRCUT
    )

    print("\n=== NO-L2 HISTORICAL BACKTEST ===")
    print(
        enabled.groupby(["trigger", "snowball"])
        .agg(
            count=("maker_pnl_120s", "count"),
            maker_mean=("maker_pnl_120s", "mean"),
            maker_sum=("maker_pnl_120s", "sum"),
            taker_mean=("taker_pnl_120s", "mean"),
            win_rate=("maker_pnl_120s", lambda x: (x > 0).mean()),
        )
        .round(4)
    )

    print("\nBy match:")
    print(
        enabled.groupby(["match_id", "trigger"])
        .agg(
            count=("maker_pnl_120s", "count"),
            maker_sum=("maker_pnl_120s", "sum"),
            maker_mean=("maker_pnl_120s", "mean"),
        )
        .sort_values("maker_sum", ascending=False)
        .round(4)
    )


if __name__ == "__main__":
    main()
