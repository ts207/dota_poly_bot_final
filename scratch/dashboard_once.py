import sqlite3
import time
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table

DB_PATH = os.getenv('DATABASE_PATH', '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
console = Console(width=120)

def get_data():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1')
        row = cursor.fetchone()
        dota = dict(row) if row else None
        
        cursor.execute("SELECT * FROM market_ticks WHERE token_id != 'COMBINED_RADIANT' ORDER BY ts_ms DESC LIMIT 10")
        market = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute('SELECT * FROM signals ORDER BY ts_ms DESC LIMIT 5')
        signals = [dict(r) for r in cursor.fetchall()]

        cursor.execute('SELECT * FROM signal_rejections ORDER BY ts_ms DESC LIMIT 5')
        rejections = [dict(r) for r in cursor.fetchall()]
        
        return {'dota': dota, 'market': market, 'signals': signals, 'rejections': rejections}
    except Exception as e:
        print(f'Error getting data: {e}')
        return None
    finally:
        conn.close()

def run():
    data = get_data()
    if not data:
        print('No data found.')
        return
    
    if data['dota']:
        d = data['dota']
        table = Table(title='Dota Live State')
        table.add_column('Team')
        table.add_column('Score')
        table.add_column('Net Worth Lead')
        table.add_column('Time')
        table.add_row('Radiant', str(d.get('radiant_score')), str(d.get('radiant_lead')), str(d.get('game_time')))
        console.print(table)

    if data['market']:
        table = Table(title='Polymarket Recent Ticks')
        table.add_column('Token')
        table.add_column('Price (Mid)')
        table.add_column('Spread')
        table.add_column('Time')
        for m in data['market']:
            mid = m.get('mid') or 0.0
            spread = m.get('spread') or 0.0
            table.add_row(m['token_id'][:10] + '...', f"{mid:.3f}", f"{spread:.3f}", datetime.fromtimestamp(m['ts_ms']/1000).strftime('%H:%M:%S'))
        console.print(table)

    if data['signals']:
        table = Table(title='Recent Signals')
        table.add_column('Time')
        table.add_column('Trigger')
        table.add_column('Edge')
        table.add_column('Expected Move')
        for s in data['signals']:
            edge = s.get('edge') or 0.0
            move = s.get('expected_move') or 0.0
            table.add_row(datetime.fromtimestamp(s['ts_ms']/1000).strftime('%H:%M:%S'), s['trigger'], f"{edge:.4f}", f"{move:.4f}")
        console.print(table)

    if data['rejections']:
        table = Table(title='Recent Rejections')
        table.add_column('Time')
        table.add_column('Reason')
        table.add_column('Edge')
        for r in data['rejections']:
            edge = r.get('edge') or 0.0
            table.add_row(datetime.fromtimestamp(r['ts_ms']/1000).strftime('%H:%M:%S'), r['reason'], f"{edge:.4f}")
        console.print(table)

if __name__ == '__main__':
    run()
