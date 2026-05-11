import sqlite3
import os
from rich.console import Console
from rich.table import Table
from datetime import datetime

DB_PATH = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
console = Console(width=150)

def investigate():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Get last 15 rejections with more detail
        cursor = conn.execute('SELECT * FROM signal_rejections ORDER BY ts_ms DESC LIMIT 15')
        rejections = [dict(r) for r in cursor.fetchall()]
        
        if rejections:
            table = Table(title='Detailed Signal Rejections Investigation')
            table.add_column('Time')
            table.add_column('Trigger')
            table.add_column('Side')
            table.add_column('Reason', style="bold red")
            table.add_column('Edge')
            table.add_column('Mid')
            table.add_column('Fair')
            table.add_column('Exp Move')
            table.add_column('Disagree')
            for r in rejections:
                ts = datetime.fromtimestamp(r['ts_ms']/1000).strftime('%H:%M:%S')
                table.add_row(
                    ts,
                    str(r.get('trigger', 'N/A')),
                    str(r.get('side', 'N/A')),
                    str(r.get('reason', 'N/A')),
                    f"{r['edge']:.4f}" if r.get('edge') is not None else 'N/A',
                    f"{r['mid']:.3f}" if r.get('mid') is not None else 'N/A',
                    f"{r['fair_price']:.3f}" if r.get('fair_price') is not None else 'N/A',
                    f"{r['expected_move']:.4f}" if r.get('expected_move') is not None else 'N/A',
                    f"{r['combined_mid_disagreement']:.4f}" if r.get('combined_mid_disagreement') is not None else 'N/A'
                )
            console.print(table)
        else:
            print('No rejections found.')
            
        # Also check successful signals if any
        cursor = conn.execute('SELECT * FROM signals ORDER BY ts_ms DESC LIMIT 5')
        signals = [dict(r) for r in cursor.fetchall()]
        if signals:
            table = Table(title='Successful Signals (Fired)')
            table.add_column('Time')
            table.add_column('Trigger')
            table.add_column('Side')
            table.add_column('Edge')
            table.add_column('Fair')
            for s in signals:
                ts = datetime.fromtimestamp(s['ts_ms']/1000).strftime('%H:%M:%S')
                table.add_row(
                    ts,
                    str(s.get('trigger', 'N/A')),
                    str(s.get('side', 'N/A')),
                    f"{s['edge']:.4f}" if s.get('edge') is not None else 'N/A',
                    f"{s['fair_price']:.3f}" if s.get('fair_price') is not None else 'N/A'
                )
            console.print(table)

    finally:
        conn.close()

if __name__ == '__main__':
    investigate()
