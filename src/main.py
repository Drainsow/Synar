import logging
from datetime import datetime, timezone

import discord
import re
from discord import app_commands

from config import ENV, DISCORD_TOKEN, DEV_GUILD_ID, LOG_LEVEL

DISCORD_TIMESTAMP_RE = re.compile(r"<t:(\d+)(?::[a-zA-Z])?>")


# ============================================================
# Logging setup
# ============================================================

def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


log = logging.getLogger("synar")


# ============================================================
# Helpers / Utilities
# ============================================================

def parse_unix_timestamp(value: str) -> int | None:
    """
    Parse and validate a Unix timestamp (seconds).

    Returns the timestamp as int if valid, otherwise None.
    """
    
    raw = value.strip()

    match = DISCORD_TIMESTAMP_RE.fullmatch(raw)
    if match:
        raw = match.group(1)

    try:
        ts = int(raw)
    except ValueError:
        return None

    # Sanity checks (optional but recommended)
    if ts < 946684800:  # 2000-01-01
        return None

    max_future = int(datetime.now(tz=timezone.utc).timestamp()) + 10 * 365 * 24 * 3600
    if ts > max_future:
        return None

    print(ts)
    return ts


async def send_invalid_timestamp(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Invalid timestamp",
        description=(
            "The timestamp you entered is not a valid Unix timestamp.\n\n"
            "Generate one here:\n"
            "https://hammertime.cyou"
        ),
        color=discord.Color.red(),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# Discord client
# ============================================================

class MyClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Slash command sync (dev vs prod)
        if ENV == "dev":
            guild = discord.Object(id=int(DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to dev guild %s", DEV_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


# ============================================================
# Client instance
# ============================================================

client = MyClient()


# ============================================================
# Slash commands
# ============================================================

@client.tree.command(name="post", description="Post a scheduled event")
@app_commands.describe(
    title="Title of the event",
    timestamp="Date of the event (required) - Unix timestamp (use hammertime.cyou)",
)
async def post(
    interaction: discord.Interaction,
    timestamp: str,
    title: str | None = None,
) -> None:
    ts = parse_unix_timestamp(timestamp)

    if ts is None:
        await send_invalid_timestamp(interaction)
        return
    
    stamp_full = f"<t:{ts}:F>"
    stamp_relative = f"<t:{ts}:R>"

    if title:
        msg = f"Post created:\nTitle: {title}\nDate: {stamp_full} - {stamp_relative}"
    else:
        msg = f"Post created:\nDate: {stamp_full} - {stamp_relative}"

    await interaction.response.send_message(msg)


# ============================================================
# Application entry point
# ============================================================

def main() -> None:
    setup_logging()
    log.info("Starting Synar (env=%s)", ENV)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()