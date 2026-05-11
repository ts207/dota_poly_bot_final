import asyncio
import json
import aiohttp
import os
import sqlite3
import time
from feeds.hero_names import hero_name

DB_PATH = os.environ.get(
    "LEAGUE_DB_PATH",
    "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite",
)
STEAM_API_URL = "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/"


_SCHEMA_GAMES = """
CREATE TABLE IF NOT EXISTS live_league_games (
    match_id INTEGER PRIMARY KEY,
    lobby_id INTEGER,
    league_id INTEGER,
    radiant_team_name TEXT,
    dire_team_name TEXT,
    game_time REAL,
    radiant_score INTEGER,
    dire_score INTEGER,
    radiant_lead INTEGER,
    spectators INTEGER,
    radiant_barracks_state INTEGER,
    dire_barracks_state INTEGER,
    radiant_tower_state INTEGER,
    dire_tower_state INTEGER,
    radiant_roshan_timer INTEGER,
    dire_roshan_timer INTEGER,
    last_update_ts INTEGER
)
"""

_SCHEMA_PLAYERS = """
CREATE TABLE IF NOT EXISTS live_league_players (
    match_id INTEGER,
    account_id INTEGER,
    name TEXT,
    hero_id INTEGER,
    hero_name TEXT,
    team INTEGER,
    net_worth INTEGER,
    gold INTEGER,
    level INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    last_hits INTEGER,
    denies INTEGER,
    gpm INTEGER,
    xpm INTEGER,
    item0 INTEGER,
    item1 INTEGER,
    item2 INTEGER,
    item3 INTEGER,
    item4 INTEGER,
    item5 INTEGER,
    PRIMARY KEY (match_id, account_id)
)
"""

_SCHEMA_DRAFT = """
CREATE TABLE IF NOT EXISTS live_draft (
    match_id INTEGER,
    team INTEGER,
    is_pick INTEGER,
    slot INTEGER,
    hero_id INTEGER,
    hero_name TEXT,
    PRIMARY KEY (match_id, team, is_pick, slot)
)
"""

_MIGRATIONS = [
    "ALTER TABLE live_league_games ADD COLUMN radiant_barracks_state INTEGER",
    "ALTER TABLE live_league_games ADD COLUMN dire_barracks_state INTEGER",
    "ALTER TABLE live_league_games ADD COLUMN radiant_tower_state INTEGER",
    "ALTER TABLE live_league_games ADD COLUMN dire_tower_state INTEGER",
    "ALTER TABLE live_league_games ADD COLUMN radiant_roshan_timer INTEGER",
    "ALTER TABLE live_league_games ADD COLUMN dire_roshan_timer INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN hero_name TEXT",
    "ALTER TABLE live_league_players ADD COLUMN last_hits INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN denies INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN gpm INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN xpm INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item0 INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item1 INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item2 INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item3 INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item4 INTEGER",
    "ALTER TABLE live_league_players ADD COLUMN item5 INTEGER",
]


def _ensure_schema(conn):
    conn.execute(_SCHEMA_GAMES)
    conn.execute(_SCHEMA_PLAYERS)
    conn.execute(_SCHEMA_DRAFT)
    for m in _MIGRATIONS:
        try:
            conn.execute(m)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def _upsert_game(conn, g, now):
    sb = g.get("scoreboard", {})
    rt = g.get("radiant_team") or {}
    dt = g.get("dire_team") or {}
    conn.execute(
        """INSERT OR REPLACE INTO live_league_games (
            match_id, lobby_id, league_id, radiant_team_name, dire_team_name,
            game_time, radiant_score, dire_score, radiant_lead, spectators,
            radiant_barracks_state, dire_barracks_state,
            radiant_tower_state, dire_tower_state,
            radiant_roshan_timer, dire_roshan_timer,
            last_update_ts
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            g.get("match_id"),
            g.get("lobby_id"),
            g.get("league_id"),
            rt.get("team_name", ""),
            dt.get("team_name", ""),
            sb.get("duration"),
            (sb.get("radiant") or {}).get("score"),
            (sb.get("dire") or {}).get("score"),
            sb.get("radiant_lead"),
            g.get("spectators"),
            (sb.get("radiant") or {}).get("barracks_state"),
            (sb.get("dire") or {}).get("barracks_state"),
            (sb.get("radiant") or {}).get("tower_state"),
            (sb.get("dire") or {}).get("tower_state"),
            (sb.get("radiant") or {}).get("roshan_respawn_timer"),
            (sb.get("dire") or {}).get("roshan_respawn_timer"),
            now,
        ),
    )


def _upsert_players(conn, g):
    sb = g.get("scoreboard", {})
    match_id = g.get("match_id")
    for side_key, team_id in (("radiant", 0), ("dire", 1)):
        for p in (sb.get(side_key) or {}).get("players", []):
            hid = p.get("hero_id", 0)
            conn.execute(
                """INSERT OR REPLACE INTO live_league_players (
                    match_id, account_id, name, hero_id, hero_name,
                    team, net_worth, gold, level, kills, deaths, assists,
                    last_hits, denies, gpm, xpm,
                    item0, item1, item2, item3, item4, item5
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    p.get("account_id"),
                    p.get("name"),
                    hid,
                    hero_name(hid) if hid else "",
                    team_id,
                    p.get("net_worth"),
                    p.get("gold"),
                    p.get("level"),
                    p.get("kills"),
                    p.get("death", p.get("deaths", 0)),
                    p.get("assists"),
                    p.get("last_hits"),
                    p.get("denies"),
                    p.get("gold_per_min"),
                    p.get("xp_per_minute"),
                    p.get("item0"),
                    p.get("item1"),
                    p.get("item2"),
                    p.get("item3"),
                    p.get("item4"),
                    p.get("item5"),
                ),
            )


def _upsert_draft(conn, g):
    sb = g.get("scoreboard", {})
    match_id = g.get("match_id")
    conn.execute("DELETE FROM live_draft WHERE match_id = ?", (match_id,))
    for side_key, team_id in (("radiant", 0), ("dire", 1)):
        side_data = sb.get(side_key) or {}
        picks = side_data.get("picks", [])
        for i, pick in enumerate(picks):
            hid = pick.get("hero_id", 0) if isinstance(pick, dict) else pick
            conn.execute(
                "INSERT INTO live_draft (match_id, team, slot, is_pick, hero_id, hero_name) VALUES (?,?,?,?,?,?)",
                (match_id, team_id, i, 1, hid, hero_name(hid) if hid else ""),
            )
        bans = side_data.get("bans", [])
        for i, ban in enumerate(bans):
            hid = ban.get("hero_id", 0) if isinstance(ban, dict) else ban
            conn.execute(
                "INSERT INTO live_draft (match_id, team, slot, is_pick, hero_id, hero_name) VALUES (?,?,?,?,?,?)",
                (match_id, team_id, i, 0, hid, hero_name(hid) if hid else ""),
            )


async def fetch_and_store(api_key=None):
    if api_key is None:
        api_key = os.environ.get("STEAM_API_KEY")
    if not api_key:
        print("STEAM_API_KEY not set")
        return 0

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(STEAM_API_URL, params={"key": api_key}) as r:
            if r.status != 200:
                print(f"Steam league API HTTP {r.status}")
                return 0
            raw = await r.read()
            data = json.loads(raw.decode("utf-8", errors="replace"))

    games = data.get("result", {}).get("games", [])
    if not games:
        return 0

    conn = sqlite3.connect(DB_PATH)
    _ensure_schema(conn)
    now = int(time.time())
    for g in games:
        if not g.get("match_id"):
            continue
        _upsert_game(conn, g, now)
        _upsert_players(conn, g)
        _upsert_draft(conn, g)
    conn.commit()
    conn.close()
    return len(games)


async def league_poll_loop(interval: float = 10.0, delay_start: float = 0.0):
    if delay_start > 0:
        print(f"League feed: sleeping {delay_start:.0f}s before first poll")
        await asyncio.sleep(delay_start)
    while True:
        try:
            n = await fetch_and_store()
            if n:
                print(f"League feed: updated {n} games")
        except Exception as e:
            print(f"League feed error: {e}")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    import sys
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    asyncio.run(league_poll_loop(interval=interval))