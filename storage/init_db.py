import os
from dotenv import load_dotenv
from storage.db import BotDatabase

load_dotenv()
BotDatabase(os.getenv("DATABASE_PATH", "dota_poly_bot/storage/bot_data.db"))
print("Database initialized.")
