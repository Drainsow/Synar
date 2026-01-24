import os
import discord
from discord import app_commands

TOKEN = os.environ.get("DISCORD_TOKEN")  # set this in your shell

class MyClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    # async def setup_hook(self) -> None:
        # Sync slash commands globally.
        # Global sync can take a while to show up in Discord.
    #    await self.tree.sync()

    async def setup_hook(self) -> None:
        guild_id = int(os.environ["GUILD_ID"])  # your test server ID
        guild = discord.Object(id=guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

client = MyClient()

@client.tree.command(name="text", description="Say hello")
@app_commands.describe(name="Optional name")
async def text(interaction: discord.Interaction, name: str | None = None):
    msg = f"Hello! {name}" if name else "Hello!"
    await interaction.response.send_message(msg)

client.run(TOKEN)