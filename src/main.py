import logging
from datetime import datetime, timezone
from typing import Literal

import discord
import re
from discord import app_commands
from discord.ext import tasks

from config import ENV, DISCORD_TOKEN, DEV_GUILD_ID, LOG_LEVEL
from storage.db import init_db, get_connection

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

    if ts < 946684800:  # 2000-01-01
        return None

    max_future = int(datetime.now(tz=timezone.utc).timestamp()) + 10 * 365 * 24 * 3600
    if ts > max_future:
        return None

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

def build_event_embed(
        title: str,
        category: str,
        timestamp: str,
        event_id: int,
        schedule_id: int | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title = title or "Event",
        description=f"**Category:** {category}\n**Date:** <t:{timestamp}:F>",
        color=discord.Color.blue(),
    )

    footer = f"Event ID: {event_id}"
    if schedule_id is not None:
        footer += f" | Schedule ID: {schedule_id}"
    embed.set_footer(text=footer)
    return embed


# ============================================================
# Tasks
# ============================================================

@tasks.loop(minutes=1)
async def scheduler_loop():
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM schedules
            WHERE end_date IS NULL OR end_date > ?
            """,
            (now_ts,),
        ).fetchall()

        for row in rows:
            step = 86400 if row["frequency"] == "daily" else 7 * 86400
            step *= row["interval"]

            next_run = row["next_run_at"]
            while next_run <= now_ts:
                next_run += step

            if row["end_date"] is not None and next_run > row["end_date"]:
                continue

            if next_run != row["next_run_at"]:
                conn.execute(
                    "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                    (next_run, row["id"]),
                )

            exists = conn.execute(
                """
                SELECT 1 FROM events
                WHERE schedule_id = ? AND timestamp = ?
                LIMIT 1
                """,
                (row["id"], next_run)
            ).fetchone()

            if not exists:
                conn.execute(
                    """
                    INSERT INTO events (
                        schedule_id,
                        guild_id, channel_id, creator_id,
                        title, category, timestamp, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["guild_id"],
                        row["channel_id"],
                        row["creator_id"],
                        row["title"],
                        row["category"],
                        next_run,
                        now_ts
                    ),
                )
                event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                channel = client.get_channel(row["channel_id"])
                if channel is None:
                    channel = await client.fetch_channel(row["channel_id"])

                embed = build_event_embed(
                    row["title"],
                    row["category"],
                    next_run,
                    event_id,
                    row["id"],
                )
                await channel.send(embed=embed)

        conn.commit()
    finally:
        conn.close()


# ============================================================
# Discord client
# ============================================================

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
        scheduler_loop.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


# ============================================================
# Client instance
# ============================================================

client = MyClient()


# ============================================================
# Views and Modals
# ============================================================



# ============================================================
# Slash commands
# ============================================================

DAILY_INTERVALS = {
    "daily": 1,
    "every 2 days": 2,
    "every 3 days": 3,
    "every 4 days": 4,
    "every 5 days": 5,
    "every 6 days": 6,
}
WEEKLY_INTERVALS = {
    "weekly": 1,
    "every 2 weeks": 2,
    "every 3 weeks": 3,
    "every 4 weeks": 4,
}
WEEKDAY_OPTIONS = [
    discord.SelectOption(label="Monday", value="0"),
    discord.SelectOption(label="Tuesday", value="1"),
    discord.SelectOption(label="Wednesday", value="2"),
    discord.SelectOption(label="Thursday", value="3"),
    discord.SelectOption(label="Friday", value="4"),
    discord.SelectOption(label="Saturday", value="5"),
    discord.SelectOption(label="Sunday", value="6"),
]

class ScheduleIntervalView(discord.ui.View):
    def __init__(self, *, title: str, category: str, frequency: str, time: str, start_date: str | None, end_date: str | None):
        super().__init__(timeout=300)
        self.title = title
        self.category = category
        self.frequency = frequency
        self.time = time
        self.start_date = start_date
        self.end_date = end_date
        self.interval_value: int | None = None
        self.day_of_week: int | None = None

        options = []
        if frequency == "daily":
            for label in DAILY_INTERVALS.keys():
                options.append(discord.SelectOption(label=label))
        else:
            for label in WEEKLY_INTERVALS.keys():
                options.append(discord.SelectOption(label=label))

        self.interval_select.options = options

        self.weekday_select.options = WEEKDAY_OPTIONS
        if self.frequency != "weekly":
            self.remove_item(self.weekday_select)

    @discord.ui.select(placeholder="Select interval")
    async def interval_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        label = select.values[0]
        if self.frequency == "daily":
            self.interval_value = DAILY_INTERVALS[label]
        else:
            self.interval_value = WEEKLY_INTERVALS[label]
        await interaction.response.defer()

    @discord.ui.select(placeholder="Select weekday")
    async def weekday_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.day_of_week = int(select.values[0])
        await interaction.response.defer()

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.interval_value is None:
            await interaction.response.send_message("Please select an interval first.", ephemeral=True)
            return
        
        if self.frequency == "weekly" and self.day_of_week is None:
            await interaction.response.send_message("Please select a weekday.", ephemeral=True)
            return
        
        time_ts = parse_unix_timestamp(self.time)
        if time_ts is None:
            await interaction.response.send_message("Time must be a valid Unix timestamp.", ephemeral=True)
            return
        
        raw_start = (self.start_date or "").strip()
        if raw_start:
            start_ts = parse_unix_timestamp(raw_start)
            if start_ts is None:
                await interaction.response.send_message(
                    "start_date must be a valid Unix timestamp.", ephemeral=True
                )
                return
        else:
            start_ts = int(datetime.now(tz=timezone.utc).timestamp())

        raw_end = (self.end_date or "").strip()
        if raw_end:
            end_ts = parse_unix_timestamp(raw_end)
            if end_ts is None:
                await interaction.response.send_message(
                    "end_date must be a valid Unix timestamp.", ephemeral=True
                )
                return
        else:
            end_ts = None

        if end_ts is not None and end_ts <= start_ts:
            await interaction.response.send_message(
                "end_date must be after start_date.", ephemeral=True
            )
            return
        
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        step_seconds = 86400 if self.frequency == "daily" else 7 * 86400
        step_seconds *= self.interval_value

        first_run_at = time_ts

        while first_run_at < start_ts:
            first_run_at += step_seconds

        while first_run_at < now_ts:
            first_run_at += step_seconds

        next_run_at = first_run_at

        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO schedules (
                    guild_id, channel_id, creator_id,
                    title, category,
                    frequency, interval, day_of_week,
                    time_of_day, start_date, end_date,
                    created_at, next_run_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild_id,
                    interaction.channel_id,
                    interaction.user.id,
                    self.title,
                    self.category,
                    self.frequency,
                    self.interval_value,
                    self.day_of_week,
                    time_ts,
                    start_ts,
                    end_ts,
                    now_ts,
                    next_run_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        await interaction.response.edit_message(content="Schedule created.", view=None)


create = app_commands.Group(name="create", description="Create events and schedules")

@create.command(name="event", description="Create a one-time event")
@app_commands.describe(
    title="Title of the event",
    category="Type of event",
    timestamp="Date of the event (Unix timestamp)",
)
async def create_event(
    interaction: discord.Interaction,
    title: str,
    category: Literal["Raid", "Dungeon", "Fractals", "Other"],
    timestamp: str,
) -> None:
    ts = parse_unix_timestamp(timestamp)

    if ts is None:
        await send_invalid_timestamp(interaction)
        return
    
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO events (
            guild_id,
            channel_id,
            creator_id,
            title,
            category,
            timestamp,
            created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild_id,
                interaction.channel_id,
                interaction.user.id,
                title,
                category,
                ts,
                now_ts,
            ),
        )
        event_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    
    stamp_full = f"<t:{ts}:F>"
    stamp_relative = f"<t:{ts}:R>"

    embed = build_event_embed(
        title=title,
        category=category,
        timestamp=ts,
        event_id=event_id,
        schedule_id=None,
    )

    await interaction.response.send_message(embed=embed)


@create.command(name="schedule", description="Create a recurring schedule")
@app_commands.describe(
    title="Title of the event",
    category="Event type",
    frequency="daily or weekly",
    time="Use @time to pick a timestamp (e. g. @time -> Enter -> 22:15 -> Enter)",
    start_date="Use @time to pick a timestamp for your starting date of your schedule (defaults to instantly)",
    end_date="Use @time to pick a timestamp for your ending date of your schedule.",
)
async def create_schedule(
    interaction: discord.Interaction,
    title: str,
    category: Literal["Raids", "Dungeons", "Fractals", "Other"],
    frequency: Literal["daily", "weekly"],
    time: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    view = ScheduleIntervalView(
        title=title,
        category=category,
        frequency=frequency,
        time=time,
        start_date=start_date,
        end_date=end_date
    )
    await interaction.response.send_message(
        "Pick an interval:", view=view, ephemeral=True
    )

client.tree.add_command(create)


@client.tree.command(name="remove", description="Remove your scheduled event")
@app_commands.describe(
    id="ID of the event",
)
async def remove(
    interaction: discord.Interaction,
    id: int
) -> None:
    msg = "removed" #wip
    await interaction.response.send_message(msg) #wip


# ============================================================
# Application entry point
# ============================================================

def main() -> None:
    setup_logging()
    init_db()
    log.info("Starting Synar (env=%s)", ENV)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()