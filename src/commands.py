from datetime import datetime, timezone
from typing import Literal
import discord
from discord import app_commands

from storage.db import get_connection
from helpers import parse_unix_timestamp, default_max_slots, send_invalid_timestamp
from embeds import build_signup_embed
from views import SignupView, EventRolePickerView, ScheduleIntervalView



def register_commands(client: discord.Client):
    client.tree.add_command(create)

create = app_commands.Group(name="create", description="Create events and schedules")

@create.command(name="event", description="Create a one-time event")
@app_commands.describe(
    title="Title of the event",
    category="Type of event",
    timestamp="Date of the event (Unix timestamp)",
    signup_mode="Restrictions for users to sign up",
)
async def create_event(
    interaction: discord.Interaction,
    title: str,
    category: Literal["Raids", "Dungeons", "Fractals", "Other"],
    timestamp: str,
    signup_mode: Literal["Open", "Role", "Invite"],
) -> None:
    ts = parse_unix_timestamp(timestamp)
    if ts is None:
        await send_invalid_timestamp(interaction)
        return

    if signup_mode == "Role":
        view = EventRolePickerView(
            title=title,
            category=category,
            timestamp=ts,
            signup_mode=signup_mode,
            creator_id=interaction.user.id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
        )
        await interaction.response.send_message(
            "Select allowed roles (max 5):",
            view=view,
            ephemeral=True,
        )
        return

    max_slots = default_max_slots(category)
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
                signup_mode,
                max_slots,
                timestamp,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild_id,
                interaction.channel_id,
                interaction.user.id,
                title,
                category,
                signup_mode.lower(),
                max_slots,
                ts,
                now_ts,
            ),
        )
        event_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    embed = await build_signup_embed(
        guild=interaction.guild,
        title=title,
        category=category,
        timestamp=ts,
        signup_mode=signup_mode,
        max_slots=default_max_slots(category),
        creator_id=interaction.user.id,
        event_id=event_id,
        allowed_role_ids=None,
        schedule_id=None,
    )

    view = SignupView(event_id)
    await interaction.response.send_message(embed=embed, view=view)


@create.command(name="schedule", description="Create a recurring schedule")
@app_commands.describe(
    title="Title of the event",
    category="Event type",
    frequency="daily or weekly",
    time="Use @time to pick a timestamp (e. g. @time -> Enter -> 22:15 -> Enter)",
    signup_mode="Restrictions for users to sign up",
    start_date="Use @time to pick a timestamp for your starting date of your schedule (defaults to instantly)",
    end_date="Use @time to pick a timestamp for your ending date of your schedule.",
)
async def create_schedule(
    interaction: discord.Interaction,
    title: str,
    category: Literal["Raids", "Dungeons", "Fractals", "Other"],
    frequency: Literal["daily", "weekly"],
    time: str,
    signup_mode: Literal["Open", "Role", "Invite"],
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    view = ScheduleIntervalView(
        title=title,
        category=category,
        frequency=frequency,
        time=time,
        signup_mode=signup_mode,
        start_date=start_date,
        end_date=end_date
    )
    await interaction.response.send_message(
        "Pick an interval:", view=view, ephemeral=True
    )