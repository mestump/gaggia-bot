import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required env var missing: {key}")
    return val

DISCORD_BOT_TOKEN = _require("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = int(_require("DISCORD_GUILD_ID"))
_alert_ch = os.getenv("DISCORD_ALERT_CHANNEL_ID", "")
DISCORD_ALERT_CHANNEL_ID = int(_alert_ch) if _alert_ch.strip() else 0
GAGGIA_IP = os.getenv("GAGGIA_IP", "192.168.4.253")
GAGGIA_POLL_INTERVAL = int(os.getenv("GAGGIA_POLL_INTERVAL", "15"))
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
DB_PATH = os.getenv("DB_PATH", "./data/gaggia.db")
GRAPH_DIR = os.getenv("GRAPH_DIR", "./data/graphs")
MIN_SHOTS_FOR_RECOMMENDATION = int(os.getenv("MIN_SHOTS_FOR_RECOMMENDATION", "3"))
