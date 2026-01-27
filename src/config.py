import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if isinstance(value, str):
        value = value.strip()
    return value


# ---- Core environment ----

ENV = (_get_env("ENV", "dev") or "dev").lower()
LOG_LEVEL = (_get_env("LOG_LEVEL", "INFO") or "INFO").upper()
SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "false").lower() in ("1", "true", "yes", "on")
CLEAR_COMMANDS = os.getenv("CLEAR_COMMANDS", "false").lower() in ("1", "true", "yes", "on")

# ---- Discord ----

DISCORD_TOKEN = _get_env("DISCORD_TOKEN")
DEV_GUILD_ID = _get_env("DEV_GUILD_ID")


# ---- Validation ----

if ENV not in ("dev", "prod"):
    raise RuntimeError(f"Invalid ENV value: {ENV!r} (expected 'dev' or 'prod')")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set")

if ENV == "dev" and not DEV_GUILD_ID:
    raise RuntimeError("DEV_GUILD_ID must be set when ENV=dev")
