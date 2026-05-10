# main.py
import asyncio
import os
import time
import traceback
from typing import Optional, Tuple

from dotenv import load_dotenv

from feeds.dota_fast import DotaFastFeed
from feeds.polymarket_ws import PolyMarketBook
from core.features import FeatureEngine
from core.signals import SignalEngine
from core.risk import RiskEngine
from core.logger import BotLogger
from core.market import combine_binary_books
from execution.order_manager import OrderManager
from storage.db import BotDatabase
from discovery.polymarket_gamma import (
    PolymarketGammaDiscovery,
    map_market_to_team_tokens,
    market_team_pair_hint,
)

load_dotenv(override=True)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def env_list_int(name: str, default: str = "0,1,2,3"):
    raw = os.getenv(name, default)
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def is_placeholder(value: str) -> bool:
    v = str(value or "").strip().lower()
    return not v or "your_" in v or "polymarket_" in v or v in {"todo", "none", "null", "0"}


async def dota_loop(feed: DotaFastFeed, features: FeatureEngine, db: BotDatabase, logger: BotLogger):
    logger.info("Starting Dota loop...")
    while True:
        try:
            tick = await feed.fetch_once()
            if tick:
                features.add_dota(tick)
                db.log_dota_tick(tick)
        except Exception as e:
            logger.error(f"Dota feed error: {e}")
        await asyncio.sleep(feed.poll_interval)


async def strategy_loop(
    dota_feed: DotaFastFeed,
    poly_book: PolyMarketBook,
    features: FeatureEngine,
    signal_engine: SignalEngine,
    risk: RiskEngine,
    orders: OrderManager,
    db: BotDatabase,
    logger: BotLogger,
    radiant_token_id: str,
    dire_token_id: str,
    market_id: str,
):
    logger.info("Starting Strategy loop...")

    while True:
        try:
            dota_tick = dota_feed.latest
            radiant_book = poly_book.get_book(radiant_token_id)
            dire_book = poly_book.get_book(dire_token_id)

            if not dota_tick or not radiant_book or not dire_book:
                if int(time.time()) % 10 == 0:
                    print(
                        "Strategy: Waiting for data... "
                        f"Dota={bool(dota_tick)} RadiantBook={bool(radiant_book)} DireBook={bool(dire_book)}"
                    )
                await asyncio.sleep(1.0)
                continue

            combined_book = combine_binary_books(radiant_book, dire_book)

            db.log_market_tick(market_id, radiant_token_id, radiant_book)
            db.log_market_tick(market_id, dire_token_id, dire_book)
            db.log_market_tick(market_id, "COMBINED_RADIANT", combined_book)

            features.add_market(combined_book)
            f = features.compute(dota_tick, combined_book)
            if not f:
                if int(time.time()) % 10 == 0:
                    print("Strategy: Processing... (Feature window filling)")
                await asyncio.sleep(1.0)
                continue

            # Inject token IDs for auditing
            f["radiant_token_id"] = radiant_token_id
            f["dire_token_id"] = dire_token_id

            if int(time.time()) % 5 == 0:
                print(
                    f"Strategy: Active | Time={int(dota_tick['game_time']//60)}m "
                    f"| CombinedMid={f['mid']:.3f} | Lead={f['nw_diff']:.0f} "
                    f"| Disagree={f['combined_mid_disagreement']:.3f}"
                )

            signal = signal_engine.generate(f)
            if signal:
                target_token_id = radiant_token_id if signal["side"] == "BUY_RADIANT_YES" else dire_token_id
                target_book = radiant_book if target_token_id == radiant_token_id else dire_book

                current_exposure = orders.get_open_exposure()
                allowed, reason = risk.allow_trade(dota_tick, combined_book, target_book, current_exposure)
                if not allowed:
                    logger.info(f"Risk blocked trade: {reason}")
                else:
                    remaining_capacity = max(0.0, risk.max_position_per_match - current_exposure)
                    size = risk.order_size(signal, target_book, remaining_capacity=remaining_capacity)
                    if size <= 0:
                        logger.info("Risk blocked trade: ZERO_SIZE_OR_HEALTH_GATE")
                    else:
                        # Hybrid Pricing: Taker for Momentum, Maker for Gaps
                        trigger = signal.get("trigger", "SLOW_BLEED")
                        fair = float(signal.get("fair_price", 0.5))
                        bid = float(target_book["best_bid"])
                        ask = float(target_book["best_ask"])

                        # Pure Maker Logic: Join the bid for ALL triggers
                        price = min(bid + 0.001, ask - 0.001)
                        mode = f"MAKER_{trigger}"

                        # Maker Edge Guard: Ensure fair value is still > 3c above our entry
                        exec_edge = fair - price
                        if exec_edge < 0.03:
                            logger.info(f"Execution blocked: MAKER_EDGE_TOO_SMALL (Edge={exec_edge:.4f}, Fair={fair:.4f}, Price={price:.4f})")
                            continue

                        logger.signal(
                            f"{signal['side']} | {mode} | Edge={exec_edge:.4f} "
                            f"| Fair={fair:.4f} | Price={price:.4f} "
                            f"| Snowball={signal.get('is_snowball_regime')}"
                        )
                        signal_id = db.log_signal(signal, f, dota_tick["match_key"], market_id, target_token_id=target_token_id)
                        result = await orders.buy_limit(target_token_id, price, size, signal, signal_id=signal_id)
                        asyncio.create_task(orders.cancel_after(result["id"], seconds=float(os.getenv("ORDER_CANCEL_AFTER_S", "2.0"))))

            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Strategy loop error: {e}")
            traceback.print_exc()
            await asyncio.sleep(2.0)


async def auto_discover_market_and_dota(
    dota_feed: DotaFastFeed,
    logger: BotLogger,
    target_match: str,
    target_radiant_team: str,
    target_dire_team: str,
) -> Optional[Tuple[str, str, str, str, str]]:
    """Discover Polymarket Dota market and align tokens to actual Dota Radiant/Dire.

    Returns (market_id, radiant_token_id, dire_token_id, radiant_team, dire_team).
    """
    logger.info("Auto-discovering active Polymarket Dota markets via Gamma API...")
    disc = PolymarketGammaDiscovery()
    try:
        markets = await disc.search_dota_markets()
    finally:
        await disc.close()

    if not markets:
        logger.error("No active Polymarket Dota markets found via Gamma API.")
        return None

    logger.info(f"Found {len(markets)} candidate Polymarket Dota markets.")

    # First use explicit configured team pair, if present.
    if target_radiant_team and target_dire_team:
        chosen = PolymarketGammaDiscovery.choose_market(markets, target_radiant_team, target_dire_team, target_match)
        if chosen:
            market, mapping = chosen
            game = await dota_feed.find_live_game_by_team_pair(target_radiant_team, target_dire_team)
            if game:
                dota_feed.set_target_server(str(game.get("server_steam_id") or ""))
                actual_r = str(game.get("team_name_radiant") or target_radiant_team)
                actual_d = str(game.get("team_name_dire") or target_dire_team)
                aligned = map_market_to_team_tokens(market, actual_r, actual_d) or mapping
                logger.info(f"Auto-selected market: {market.question} | {market.url}")
                logger.info(f"Dota alignment: Radiant={actual_r} Dire={actual_d} server={game.get('server_steam_id')}")
                return aligned["MARKET_ID"], aligned["RADIANT_TOKEN_ID"], aligned["DIRE_TOKEN_ID"], actual_r, actual_d
            logger.info("Polymarket match found, but matching Dota live game was not visible yet. Using configured team mapping.")
            return mapping["MARKET_ID"], mapping["RADIANT_TOKEN_ID"], mapping["DIRE_TOKEN_ID"], target_radiant_team, target_dire_team

    # Otherwise iterate Dota market candidates and try to find the matching live Dota game.
    for market in markets:
        team_a, team_b = market_team_pair_hint(market)
        if target_match:
            hay = " ".join([market.question, market.slug, " ".join(market.outcomes)]).lower()
            if target_match.lower() not in hay:
                continue
        if not team_a or not team_b:
            continue
        game = await dota_feed.find_live_game_by_team_pair(team_a, team_b)
        if not game:
            continue
        actual_r = str(game.get("team_name_radiant") or "")
        actual_d = str(game.get("team_name_dire") or "")
        mapping = map_market_to_team_tokens(market, actual_r, actual_d)
        if not mapping:
            continue
        dota_feed.set_target_server(str(game.get("server_steam_id") or ""))
        logger.info(f"Auto-selected market: {market.question} | {market.url}")
        logger.info(f"Dota alignment: Radiant={actual_r} Dire={actual_d} server={game.get('server_steam_id')}")
        logger.info(f"Mapped outcomes: Radiant={mapping.get('RADIANT_OUTCOME')} Dire={mapping.get('DIRE_OUTCOME')}")
        return mapping["MARKET_ID"], mapping["RADIANT_TOKEN_ID"], mapping["DIRE_TOKEN_ID"], actual_r, actual_d

    # Last resort is disabled by default because it can silently collect the wrong match.
    if env_bool("ALLOW_UNCONFIRMED_POLYMARKET_MAPPING", False):
        chosen = PolymarketGammaDiscovery.choose_market(markets, target_radiant_team, target_dire_team, target_match)
        if chosen:
            market, mapping = chosen
            logger.info(f"Auto-selected Polymarket market, but Dota server alignment is NOT confirmed: {market.question} | {market.url}")
            return mapping["MARKET_ID"], mapping["RADIANT_TOKEN_ID"], mapping["DIRE_TOKEN_ID"], mapping.get("RADIANT_OUTCOME", ""), mapping.get("DIRE_OUTCOME", "")
    else:
        logger.error("Polymarket market found, but Dota live-game alignment is unconfirmed. Refusing to start. Set ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=true to override for research only.")

    top = markets[:5]
    logger.error("Could not confidently map a Polymarket Dota market to Dota teams. Top candidates:")
    for m in top:
        logger.error(f"  {m.question} | outcomes={m.outcomes} | {m.url}")
    return None


async def main():
    steam_key = os.getenv("STEAM_API_KEY")
    if not steam_key or is_placeholder(steam_key):
        print("Error: STEAM_API_KEY not found in .env")
        return

    target_match = os.getenv("TARGET_MATCH", "").strip()
    target_radiant_team = os.getenv("TARGET_RADIANT_TEAM", "").strip()
    target_dire_team = os.getenv("TARGET_DIRE_TEAM", "").strip()
    target_server_steam_id = os.getenv("TARGET_SERVER_STEAM_ID", "").strip()

    logger = BotLogger()
    db = BotDatabase(os.getenv("DATABASE_PATH", "dota_poly_bot/storage/bot_data.db"))

    dota_feed = DotaFastFeed(
        steam_key,
        target_match_name=target_match,
        target_radiant_team=target_radiant_team,
        target_dire_team=target_dire_team,
        target_server_steam_id=target_server_steam_id,
        poll_interval=float(os.getenv("DOTA_POLL_INTERVAL", "1.0")),
        partners=env_list_int("DOTA_PARTNERS", "0,1,2,3"),
    )

    market_id = os.getenv("MARKET_ID", "").strip()
    radiant_token_id = os.getenv("RADIANT_TOKEN_ID", "").strip()
    dire_token_id = os.getenv("DIRE_TOKEN_ID", "").strip()
    
    auto_discover = env_bool("AUTO_DISCOVER_POLYMARKET", True) or any(
        is_placeholder(x) for x in (market_id, radiant_token_id, dire_token_id)
    )

    if auto_discover:
        discovered = await auto_discover_market_and_dota(
            dota_feed,
            logger,
            target_match=target_match,
            target_radiant_team=target_radiant_team,
            target_dire_team=target_dire_team,
        )
        if not discovered:
            print("Error: automatic Polymarket/Dota discovery failed. Set MARKET_ID/RADIANT_TOKEN_ID/DIRE_TOKEN_ID and exact Dota target manually.")
            await dota_feed.close()
            return
        market_id, radiant_token_id, dire_token_id, target_radiant_team, target_dire_team = discovered
    else:
        if not target_server_steam_id and not (target_radiant_team and target_dire_team) and not target_match:
            print("Error: Set TARGET_SERVER_STEAM_ID or TARGET_RADIANT_TEAM + TARGET_DIRE_TEAM, or enable AUTO_DISCOVER_POLYMARKET=true.")
            await dota_feed.close()
            return
        if any(is_placeholder(x) for x in (market_id, radiant_token_id, dire_token_id)):
            print("Error: Set MARKET_ID/RADIANT_TOKEN_ID/DIRE_TOKEN_ID or enable AUTO_DISCOVER_POLYMARKET=true.")
            await dota_feed.close()
            return

    logger.info(f"Using market_id={market_id}")
    logger.info(f"Radiant token={radiant_token_id[:10]}... Dire token={dire_token_id[:10]}...")

    poly_book = PolyMarketBook(
        [radiant_token_id, dire_token_id],
        snapshot_interval_s=float(os.getenv("PM_SNAPSHOT_INTERVAL_S", "120")),
        validation_tolerance=float(os.getenv("PM_BOOK_VALIDATION_TOLERANCE", "0.01")),
    )
    features = FeatureEngine()
    signals = SignalEngine()
    risk = RiskEngine()
    orders = OrderManager(poly_client=None, dry_run=True, db=db, market_id=market_id)

    try:
        await asyncio.gather(
            dota_loop(dota_feed, features, db, logger),
            poly_book.run(),
            strategy_loop(
                dota_feed,
                poly_book,
                features,
                signals,
                risk,
                orders,
                db,
                logger,
                radiant_token_id,
                dire_token_id,
                market_id,
            ),
        )
    finally:
        await dota_feed.close()
        await poly_book.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
