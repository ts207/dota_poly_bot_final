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

DB_PATH = os.getenv("DATABASE_PATH", ./data/dota_poly_collection.sqlite")
console = Console()

def get_data():
    if not os.path.exists(DB_PATH):
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Latest Dota Tick
        cursor.execute("SELECT * FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1")
        row = cursor.fetchone()
        dota = dict(row) if row else None

        # Latest Market Ticks for Combined Radiant
        cursor.execute("SELECT * FROM market_ticks WHERE token_id = 'COMBINED_RADIANT' ORDER BY ts_ms DESC LIMIT 1")
        row = cursor.fetchone()
        market = dict(row) if row else None

        # Latest Signals
        cursor.execute("SELECT * FROM signals ORDER BY ts_ms DESC LIMIT 5")
        signals = [dict(r) for r in cursor.fetchall()]

        # Recent Orders
        cursor.execute("SELECT * FROM orders ORDER BY ts_ms DESC LIMIT 5")
        orders = [dict(r) for r in cursor.fetchall()]

        # Summary Stats
        cursor.execute("SELECT COUNT(*) as count, SUM(filled_size * fill_price) as volume FROM orders WHERE status = 'FILLED'")
        row = cursor.fetchone()
        summary = dict(row) if row else None

        return {
            "dota": dota,
            "market": market,
            "signals": signals,
            "orders": orders,
            "summary": summary
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def generate_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", size=10),
        Layout(name="footer", size=15)
    )
    layout["main"].split_row(
        Layout(name="game_state"),
        Layout(name="market_state")
    )
    layout["footer"].split_row(
        Layout(name="signals"),
        Layout(name="orders")
    )
    return layout

def make_header(data):
    if not data or not data.get("dota"):
        return Panel(Text("Waiting for data (Dota: ✘ | Poly: ?) ...", justify="center", style="bold red"))
    
    dota = data["dota"]
    market = data.get("market")
    poly_status = "✔" if market else "✘"
    match_title = f"{dota['radiant_team']} vs {dota['dire_team']}"
    return Panel(
        Text(f"DOTA POLY BOT | {match_title} | Dota: ✔ | Poly: {poly_status} | {datetime.now().strftime('%H:%M:%S')}", justify="center", style="bold white"),
        style="blue"
    )

def make_game_state(data):
    if not data or not data.get("dota"):
        return Panel("No Dota Data")
    
    d = data["dota"]
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Game Time", f"{int(d['game_time']//60)}:{int(d['game_time']%60):02d}")
    table.add_row("Score", f"[bold green]{d['radiant_score']}[/bold green] - [bold red]{d['dire_score']}[/bold red]")
    
    lead_style = "bold green" if d['nw_diff'] > 0 else "bold red"
    table.add_row("Radiant Lead", Text(f"{d['nw_diff']:,.0f}", style=lead_style))
    
    return Panel(table, title="[bold]Game State[/bold]", border_style="green")

def make_market_state(data):
    if not data or not data.get("market"):
        return Panel("No Market Data")
    
    m = data["market"]
    table = Table(show_header=False, box=box.SIMPLE)
    table.add_row("Combined Mid", f"{m['mid']:.3f}")
    table.add_row("Spread", f"{m['spread']:.4f}")
    
    depth_style = "dim" if m['bid_depth'] < 100 else "bold cyan"
    table.add_row("Bid Depth", Text(f"${m['bid_depth']:,.0f}", style=depth_style))
    
    return Panel(table, title="[bold]Market State[/bold]", border_style="cyan")

def make_signals_table(data):
    table = Table(title="Recent Signals", box=box.SIMPLE, expand=True)
    table.add_column("Time", style="dim")
    table.add_column("Trigger")
    table.add_column("Side")
    table.add_column("Mid")
    table.add_column("Fair")
    table.add_column("Edge")

    if data and data.get("signals"):
        for s in data["signals"]:
            edge_style = "bold green" if s['edge'] > 0.05 else "white"
            side_style = "green" if "RADIANT" in s['side'] else "red"
            table.add_row(
                datetime.fromtimestamp(s['ts_ms']/1000).strftime('%H:%M:%S'),
                f"{s['trigger']}:{s['trigger_strength']}",
                Text(s['side'], style=side_style),
                f"{s['market_lag'] + s['fair_price'] - s['edge']:.3f}", # approx mid
                f"{s['fair_price']:.3f}",
                Text(f"{s['edge']*100:+.1f}%", style=edge_style)
            )
    return Panel(table)

def make_orders_table(data):
    table = Table(title="Recent Orders", box=box.SIMPLE, expand=True)
    table.add_column("Time", style="dim")
    table.add_column("Side")
    table.add_column("Price")
    table.add_column("Size")
    table.add_column("Status")

    if data and data.get("orders"):
        for o in data["orders"]:
            status_style = "bold green" if o['status'] == "FILLED" else "dim"
            table.add_row(
                datetime.fromtimestamp(o['ts_ms']/1000).strftime('%H:%M:%S'),
                o['side'],
                f"{o['price']:.3f}",
                f"{o['size']:.1f}",
                Text(o['status'], style=status_style)
            )
    return Panel(table)

layout = generate_layout()

with Live(layout, refresh_per_second=1, screen=True):
    while True:
        data = get_data()
        layout["header"].update(make_header(data))
        layout["game_state"].update(make_game_state(data))
        layout["market_state"].update(make_market_state(data))
        layout["signals"].update(make_signals_table(data))
        layout["orders"].update(make_orders_table(data))
        time.sleep(1)
