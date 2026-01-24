import logging

import discord
from discord import app_commands

from config import ENV, DISCORD_TOKEN, DEV_GUILD_ID, LOG_LEVEL


def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


log = logging.getLogger("synar")


class MyClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
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


client = MyClient()


@client.tree.command(name="post", description="Post a scheduled event")
@app_commands.describe(title="Title of the event", date="Date of the event (required)")
async def post(interaction: discord.Interaction, date: str, title: str | None = None) -> None:
    if title:
        msg = f"Post created:\nTitle: {title}\nDate: {date}"
    else:
        msg = f"Post created:\nDate: {date}"
    await interaction.response.send_message(msg)


def main() -> None:
    setup_logging()
    log.info("Starting Synar (env=%s)", ENV)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
