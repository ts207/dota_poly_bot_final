# core/logger.py
from rich.console import Console
from datetime import datetime

class BotLogger:
    def __init__(self):
        self.console = Console()

    def info(self, msg: str):
        self.console.print(f"[cyan][{datetime.now().strftime('%H:%M:%S')}][/cyan] {msg}")

    def signal(self, msg: str):
        self.console.print(f"[bold yellow][SIGNAL][/bold yellow] {msg}")

    def trade(self, msg: str):
        self.console.print(f"[bold green][TRADE][/bold green] {msg}")

    def warning(self, msg: str):
        self.console.print(f"[yellow][WARN][/yellow] {msg}")

    def error(self, msg: str):
        self.console.print(f"[bold red][ERROR][/bold red] {msg}")
