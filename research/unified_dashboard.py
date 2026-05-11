import sqlite3
import time
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box
from discovery.polymarket_gamma import PolymarketGammaDiscovery
import asyncio

DB_PATH = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
ENV_PATH = "/home/irene/dota_poly_bot_final/data/last_discovered_target.env"
console = Console()


def load_env_mapping():
    mapping = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                mapping[k.strip()] = v.strip()
    return mapping


def decode_towers(state):
    if state is None or state == 0:
        return 0
    return sum(1 for i in range(11) if state & (1 << i))


def decode_barracks(state):
    if state is None or state == 0:
        return 0
    return sum(1 for i in range(6) if state & (1 << i))


MAX_TOWERS = 11
MAX_BARRACKS = 6


class UnifiedDashboard:
    def __init__(self):
        self.discovery = PolymarketGammaDiscovery()
        self.active_markets = []
        self.last_discovery_ts = 0
        self.env_mapping = load_env_mapping()

    async def update_discovery(self):
        now = time.time()
        if now - self.last_discovery_ts > 300:
            try:
                self.active_markets = await self.discovery.search_dota_markets(active=True, strict_match_winner_only=False)
                self.last_discovery_ts = now
            except Exception:
                pass

    def get_data(self):
        self.env_mapping = load_env_mapping()
        if not os.path.exists(DB_PATH):
            return None

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1")
            row = cursor.fetchone()
            dota = dict(row) if row else None

            cursor.execute("SELECT * FROM market_ticks WHERE token_id LIKE 'COMBINED%' ORDER BY ts_ms DESC LIMIT 1")
            row = cursor.fetchone()
            market = dict(row) if row else None

            cursor.execute("SELECT token_id, best_bid, best_ask, mid, spread, bid_depth, ask_depth, ts_ms FROM market_ticks WHERE token_id NOT LIKE 'COMBINED%' ORDER BY ts_ms DESC LIMIT 10")
            token_rows = cursor.fetchall()
            token_prices = {}
            seen = set()
            for tr in token_rows:
                tid = tr[0]
                if tid in seen:
                    continue
                seen.add(tid)
                token_prices[tid] = {
                    "bid": tr[1], "ask": tr[2], "mid": tr[3],
                    "spread": tr[4], "bid_depth": tr[5], "ask_depth": tr[6], "ts_ms": tr[7]
                }

            cursor.execute("SELECT * FROM live_league_games ORDER BY last_update_ts DESC")
            league_games = [dict(r) for r in cursor.fetchall()]

            league_game = None
            players = []
            draft = []
            if dota:
                match_id = None
                r_clean = dota['radiant_team'].lower().replace('_', '').strip()
                d_clean = dota['dire_team'].lower().replace('_', '').strip()
                for lg in league_games:
                    lg_r = lg['radiant_team_name'].lower().replace('_', '').strip()
                    lg_d = lg['dire_team_name'].lower().replace('_', '').strip()
                    if lg_r and (r_clean in lg_r or lg_r in r_clean) and (not lg_d or d_clean in lg_d or lg_d in d_clean):
                        match_id = lg['match_id']
                        league_game = lg
                        break

                if match_id:
                    cursor.execute("SELECT * FROM live_league_players WHERE match_id = ? ORDER BY team, net_worth DESC", (match_id,))
                    players = [dict(r) for r in cursor.fetchall()]
                    cursor.execute("SELECT * FROM live_draft WHERE match_id = ? ORDER BY team, slot", (match_id,))
                    draft = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM signals ORDER BY ts_ms DESC LIMIT 10")
            signals = [dict(r) for r in cursor.fetchall()]
            cursor.execute("SELECT * FROM orders ORDER BY ts_ms DESC LIMIT 10")
            orders = [dict(r) for r in cursor.fetchall()]

            return {
                "dota": dota,
                "market": market,
                "token_prices": token_prices,
                "league_game": league_game,
                "players": players,
                "draft": draft,
                "signals": signals,
                "orders": orders
            }
        except Exception as e:
            return {"error": str(e)}
        finally:
            conn.close()

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="upper", size=18),
            Layout(name="lower", size=15)
        )
        layout["upper"].split_row(
            Layout(name="game_state", ratio=2),
            Layout(name="draft_state", ratio=2),
            Layout(name="market_state", ratio=2),
            Layout(name="top_players", ratio=4)
        )
        layout["lower"].split_row(
            Layout(name="signals", ratio=1),
            Layout(name="orders", ratio=1)
        )
        return layout

    def make_header(self, data):
        title = "DOTA POLY UNIFIED DASHBOARD"
        if data and data.get("dota"):
            d = data["dota"]
            title += f" | {d['radiant_team']} vs {d['dire_team']}"
        return Panel(Text(f"{title} | {datetime.now().strftime('%H:%M:%S')}", justify="center", style="bold white"), style="blue")

    def make_game_state(self, data):
        if not data or not data.get("dota"):
            return Panel("No Live Feed")
        d = data["dota"]
        lg = data.get("league_game")
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_row("Time", f"{int(d['game_time']//60)}:{int(d['game_time']%60):02d}")
        table.add_row("Score", f"[green]{d['radiant_score']}[/] - [red]{d['dire_score']}[/]")
        table.add_row("Gold Lead", f"[bold]{d['nw_diff']:,.0f}[/]")
        if lg:
            web_lag_s = d['ts_ms'] / 1000 - lg['last_update_ts']
            lag_color = "green" if web_lag_s < 15 else ("yellow" if web_lag_s < 45 else "red")
            table.add_row("Web API Lag", f"[{lag_color}]+{web_lag_s:.0f}s[/]")
        else:
            table.add_row("Web API Lag", "[red]no data[/]")
        table.add_row("─── Buildings ───", "")
        if lg:
            r_towers_up = decode_towers(lg.get('radiant_tower_state'))
            r_rax_up = decode_barracks(lg.get('radiant_barracks_state'))
            d_towers_up = decode_towers(lg.get('dire_tower_state'))
            d_rax_up = decode_barracks(lg.get('dire_barracks_state'))
            table.add_row("Rad Towers", f"[green]{r_towers_up}[/]/{MAX_TOWERS}")
            table.add_row("Rad Rax", f"[green]{r_rax_up}[/]/{MAX_BARRACKS}")
            table.add_row("Dire Towers", f"[red]{d_towers_up}[/]/{MAX_TOWERS}")
            table.add_row("Dire Rax", f"[red]{d_rax_up}[/]/{MAX_BARRACKS}")
            r_rosh = lg.get('radiant_roshan_timer')
            d_rosh = lg.get('dire_roshan_timer')
            rosh_status = "Alive" if (r_rosh is not None and r_rosh == 0) or (d_rosh is not None and d_rosh == 0) else ""
            if r_rosh and r_rosh > 0:
                rosh_status = f"[green]{r_rosh // 60}:{r_rosh % 60:02d}[/]"
            elif d_rosh and d_rosh > 0:
                rosh_status = f"[red]{d_rosh // 60}:{d_rosh % 60:02d}[/]"
            table.add_row("Roshan", rosh_status or "—")
        else:
            table.add_row("Buildings", " awaiting web API")
        return Panel(table, title="Match State", border_style="green")

    def make_draft(self, data):
        draft = data.get("draft", []) if data else []
        if not draft:
            return Panel("No Draft Data", title="Draft", border_style="green")
        rad_picks = [d for d in draft if d['team'] == 0 and d['is_pick'] == 1]
        dire_picks = [d for d in draft if d['team'] == 1 and d['is_pick'] == 1]
        rad_bans = [d for d in draft if d['team'] == 0 and d['is_pick'] == 0]
        dire_bans = [d for d in draft if d['team'] == 1 and d['is_pick'] == 0]
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("", max_width=6)
        table.add_column("Radiant", style="green")
        table.add_column("Dire", style="red")
        if rad_bans or dire_bans:
            rb = ", ".join(d['hero_name'] or str(d['hero_id']) for d in rad_bans) or "—"
            db = ", ".join(d['hero_name'] or str(d['hero_id']) for d in dire_bans) or "—"
            table.add_row("Bans", rb, db)
        rp = ", ".join(d['hero_name'] or str(d['hero_id']) for d in rad_picks) or "—"
        dp = ", ".join(d['hero_name'] or str(d['hero_id']) for d in dire_picks) or "—"
        table.add_row("Picks", rp, dp)
        return Panel(table, title="Draft", border_style="green")

    def make_market_state(self, data):
        if not data or not data.get("market"):
            return Panel("No Market")
        m = data["market"]
        tp = data.get("token_prices", {})
        env = self.env_mapping
        radiant_tid = env.get("RADIANT_TOKEN_ID", "")
        dire_tid = env.get("DIRE_TOKEN_ID", "")
        radiant_team = env.get("TARGET_RADIANT_TEAM", "")
        dire_team = env.get("TARGET_DIRE_TEAM", "")
        if data.get("dota"):
            radiant_team = radiant_team or data["dota"].get("radiant_team", "Radiant")
            dire_team = dire_team or data["dota"].get("dire_team", "Dire")
        else:
            radiant_team = radiant_team or "Radiant"
            dire_team = dire_team or "Dire"
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_row("Radiant Prob", f"{m['mid']:.1%}")
        table.add_row("Spread", f"{m['spread']:.4f}")
        table.add_row("Liquidity", f"${m['bid_depth']+m['ask_depth']:,.0f}")
        table.add_row("─── Poly Prices ───", "")
        sorted_tokens = sorted(tp.items(), key=lambda x: -x[1].get("mid", 0))
        for tid, info in sorted_tokens:
            if tid == radiant_tid:
                label = f"[green]{radiant_team}[/]"
            elif tid == dire_tid:
                label = f"[red]{dire_team}[/]"
            else:
                label = tid[:8] + "…"
            table.add_row(label, f"B:{info['bid']:.2f} A:{info['ask']:.2f} M:{info['mid']:.3f}")
        return Panel(table, title="Polymarket", border_style="cyan")

    def make_top_players(self, data):
        if not data or not data.get("players"):
            return Panel("No Player Stats (awaiting web API data…)")
        players = data["players"]
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Hero", style="bold cyan", max_width=14)
        table.add_column("Team", max_width=4)
        table.add_column("Lvl", justify="right", max_width=3)
        table.add_column("KDA", justify="center", max_width=7)
        table.add_column("NW", justify="right", style="yellow", max_width=7)
        table.add_column("LH/D", justify="right", max_width=6)
        table.add_column("GPM", justify="right", max_width=5)
        table.add_column("XPM", justify="right", max_width=5)
        for p in players:
            team = "[green]R[/]" if p['team'] == 0 else "[red]D[/]"
            hero = p.get('hero_name') or p.get('name', '?')
            hero_short = hero[:14]
            deaths = p.get('deaths') or p.get('death', 0) or 0
            kda = f"{p['kills']}/{deaths}/{p['assists']}"
            lh = p.get('last_hits') or 0
            dn = p.get('denies') or 0
            gpm = p.get('gpm') or p.get('gold_per_minute') or 0
            xpm = p.get('xpm') or p.get('xp_per_minute') or 0
            table.add_row(
                hero_short, team, str(p.get('level', '')),
                kda, f"{p['net_worth']:,}",
                f"{lh}/{dn}", str(gpm), str(xpm)
            )
        return Panel(table, title="Live Players (Steam Web API)", border_style="magenta")

    def make_signals(self, data):
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Time")
        table.add_column("Trigger")
        table.add_column("Edge")
        table.add_column("Action")
        if data and data.get("signals"):
            for s in data['signals']:
                t = datetime.fromtimestamp(s['ts_ms']/1000).strftime('%H:%M:%S')
                edge_style = "bold green" if s['edge'] > 0.05 else "white"
                table.add_row(t, s['trigger'], Text(f"{s['edge']*100:+.1f}%", style=edge_style), s['action'])
        return Panel(table, title="Recent Signals", border_style="yellow")

    def make_orders(self, data):
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Time")
        table.add_column("Side")
        table.add_column("Price")
        table.add_column("Status")
        if data and data.get("orders"):
            for o in data['orders']:
                t = datetime.fromtimestamp(o['ts_ms']/1000).strftime('%H:%M:%S')
                status_style = "bold green" if o['status'] == "FILLED" else "white"
                table.add_row(t, o['side'], f"{o['price']:.3f}", Text(o['status'], style=status_style))
        return Panel(table, title="Order log", border_style="white")


async def run_dashboard():
    dash = UnifiedDashboard()
    layout = dash.generate_layout()
    with Live(layout, refresh_per_second=1, screen=True):
        while True:
            await dash.update_discovery()
            data = dash.get_data()
            layout["header"].update(dash.make_header(data))
            layout["game_state"].update(dash.make_game_state(data))
            layout["draft_state"].update(dash.make_draft(data))
            layout["market_state"].update(dash.make_market_state(data))
            layout["top_players"].update(dash.make_top_players(data))
            layout["signals"].update(dash.make_signals(data))
            layout["orders"].update(dash.make_orders(data))
            await asyncio.sleep(1)


if __name__ == '__main__':
    asyncio.run(run_dashboard())