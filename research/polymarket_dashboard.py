import asyncio
import os
import sqlite3
import pandas as pd
import re
from rich.console import Console
from rich.table import Table
from discovery.polymarket_gamma import PolymarketGammaDiscovery
from dotenv import load_dotenv

load_dotenv()
console = Console()

def clean_name(name):
    if not name: return ""
    n = name.lower().replace('_', ' ').strip()
    n = re.sub(r'\b(gaming|esports|team|club|pro)\b', '', n).strip()
    return n

async def show_polymarket_live_dashboard():
    db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
    discovery = PolymarketGammaDiscovery()
    try:
        markets = await discovery.search_dota_markets(query_terms=["dota", "modus", "power rangers"], strict_match_winner_only=False)
    finally:
        await discovery.close()
    
    conn = sqlite3.connect(db_path)
    try:
        games_df = pd.read_sql_query("SELECT * FROM live_league_games", conn)
        
        table = Table(title="Dota 2 Polymarket-Linked Live Dashboard")
        table.add_column("Match ID", style="cyan")
        table.add_column("Market Slug", style="magenta")
        table.add_column("Radiant", style="green")
        table.add_column("Dire", style="red")
        table.add_column("Time", justify="right")
        table.add_column("Score", justify="center")

        found_linked = 0
        for _, row in games_df.iterrows():
            r_raw, d_raw = str(row['radiant_team_name']), str(row['dire_team_name'])
            r_clean, d_clean = clean_name(r_raw), clean_name(d_raw)
            
            if r_clean == "unknown" or d_clean == "unknown": continue
            
            for m in markets:
                slug, title = m.slug.lower(), m.question.lower()
                
                # Debug print for specific match
                if 'modus' in r_clean or 'power' in r_clean or 'modus' in d_clean or 'power' in d_clean:
                    if 'modus' in slug and ('pr' in slug or 'power' in slug):
                        # This IS a candidate. Check if it matches OUR teams.
                        m_r = (r_clean in slug or r_clean in title or (r_clean == 'power rangers' and 'pr' in slug))
                        m_d = (d_clean in slug or d_clean in title or (d_clean == 'power rangers' and 'pr' in slug))
                        
                        if m_r and m_d:
                            found_linked += 1
                            table.add_row(str(row['match_id']), m.slug, r_raw, d_raw, f"{int(row['game_time']/60) if row['game_time'] else 0}m", f"{int(row['radiant_score']) if row['radiant_score'] else 0} - {int(row['dire_score']) if row['dire_score'] else 0}")
                            break

        if found_linked == 0:
            console.print("[yellow]No linked matches found.[/yellow]")
        else:
            console.print(table)
    finally:
        conn.close()

if __name__ == '__main__':
    asyncio.run(show_polymarket_live_dashboard())
