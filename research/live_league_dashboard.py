import sqlite3
import pandas as pd
from rich.console import Console
from rich.table import Table
import time
import numpy as np

console = Console()

def show_dashboard():
    db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
    conn = sqlite3.connect(db_path)
    
    try:
        # Get live games
        games_df = pd.read_sql_query("""
            SELECT 
                match_id, 
                radiant_team_name, 
                dire_team_name, 
                game_time / 60 as game_min,
                radiant_score,
                dire_score,
                radiant_lead,
                spectators
            FROM live_league_games
            ORDER BY last_update_ts DESC
        """, conn)
        
        if games_df.empty:
            console.print("[yellow]No live league games found in database.[/yellow]")
            return

        table = Table(title="Dota 2 Live League Dashboard (Web API)")
        table.add_column("Match ID", style="cyan")
        table.add_column("Radiant", style="green")
        table.add_column("Dire", style="red")
        table.add_column("Time", justify="right")
        table.add_column("Score", justify="center")
        table.add_column("Lead", justify="right")
        table.add_column("Spectators", justify="right")

        for _, row in games_df.iterrows():
            game_min_val = row['game_min']
            time_str = f"{int(game_min_val)}m" if not pd.isna(game_min_val) else "0m"
            score_str = f"{int(row['radiant_score'])} - {int(row['dire_score'])}" if not pd.isna(row['radiant_score']) and not pd.isna(row['dire_score']) else "0 - 0"
            lead_str = f"{int(row['radiant_lead']):+d}" if not pd.isna(row['radiant_lead']) else "0"
            
            table.add_row(
                str(row['match_id']),
                str(row['radiant_team_name']),
                str(row['dire_team_name']),
                time_str,
                score_str,
                lead_str,
                str(row['spectators'])
            )

        console.print(table)
        
        # Show top players by Net Worth for a specific match (e.g. Map 2 of PR vs MODUS)
        # Note: Match ID for Map 2 was 8806661972
        console.print("\n[bold]Top Players (Net Worth) - PR vs MODUS Map 2[/bold]")
        players_df = pd.read_sql_query("""
            SELECT name, team, net_worth, level, kills, deaths, assists
            FROM live_league_players
            WHERE match_id = 8806661972
            ORDER BY net_worth DESC
            LIMIT 10
        """, conn)
        
        if not players_df.empty:
            p_table = Table()
            p_table.add_column("Player", style="white")
            p_table.add_column("Team", style="magenta")
            p_table.add_column("Net Worth", justify="right")
            p_table.add_column("Level", justify="right")
            p_table.add_column("KDA", justify="center")
            
            for _, p in players_df.iterrows():
                team_str = "Radiant" if p['team'] == 0 else "Dire"
                p_table.add_row(
                    str(p['name']),
                    team_str,
                    f"{int(p['net_worth']):,}" if not pd.isna(p['net_worth']) else "0",
                    str(int(p['level'])) if not pd.isna(p['level']) else "1",
                    f"{int(p['kills'])}/{int(p['deaths'])}/{int(p['assists'])}" if not pd.isna(p['kills']) else "0/0/0"
                )
            console.print(p_table)

    finally:
        conn.close()

if __name__ == '__main__':
    show_dashboard()
