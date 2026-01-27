import logging
import time
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

    if ts < 946684800:
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

async def build_signup_embed(
    *,
    guild: discord.Guild | None,
    title: str,
    category: str,
    timestamp: int,
    signup_mode: str,
    max_slots: int,
    creator_id: int,
    event_id: int,
    allowed_role_ids: list[int] | None = None,
    schedule_id: int | None = None,
) -> discord.Embed:
    def display_name(user_id: int) -> str:
        if guild:
            m = guild.get_member(user_id)
            if m:
                return m.display_name
        return f"<@{user_id}>"

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT user_id, status FROM event_signups WHERE event_id = ?",
            (event_id,),
        ).fetchall()
    finally:
        conn.close()

    available = [display_name(r["user_id"]) for r in rows if r["status"] == "available"]
    unavailable = [display_name(r["user_id"]) for r in rows if r["status"] == "unavailable"]
    maybe = [display_name(r["user_id"]) for r in rows if r["status"] == "maybe"]

    embed = discord.Embed(
        title=title or "Event",
        description=(
            f"**Category:** {category}\n"
            f"**Signup-Mode:** {(signup_mode or 'open').capitalize()}\n"
            f"**Date:** <t:{timestamp}:F>\n"
            f"**Signups:** {len(available)}/{max_slots}"
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(name="Available", value="\n".join(available) or "-", inline=True)
    embed.add_field(name="Unavailable", value="\n".join(unavailable) or "-", inline=True)
    embed.add_field(name="Maybe", value="\n".join(maybe) or "-", inline=True)

    embed.add_field(
        name="Allowed Roles",
        value=role_names_text(guild, allowed_role_ids, signup_mode),
        inline=False,
    )

    creator_name = None
    if guild:
        m = guild.get_member(creator_id)
        if not m:
            try:
                m = await guild.fetch_member(creator_id)
            except discord.NotFound:
                m = None
        if m:
            creator_name = m.display_name

    footer = f"Event ID: {event_id}"
    if schedule_id is not None:
        footer += f" | Schedule ID: {schedule_id}"
    if creator_name:
        footer += f" | Host: {creator_name}"
    embed.set_footer(text=footer)

    return embed


def default_max_slots(category: str) -> int:
    if category == "Raids":
        return 10
    if category in ("Dungeons", "Fractals"):
        return 5
    return 50


def role_names_text(guild: discord.Guild | None, role_ids: list[int] | None, signup_mode: str) -> str:
    if signup_mode.lower() == "invite":
        return "Invite Only"
    if not role_ids:
        return "Everyone"
    if not guild:
        return "Roles set"
    names = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            names.append(role.name)
    return ", ".join(names) if names else "Roles set"


def user_has_allowed_role(member: discord.Member | None, allowed_role_ids: list[int]) -> bool:
    if not member:
        return False
    member_role_ids = {r.id for r in member.roles}
    return any(rid in member_role_ids for rid in allowed_role_ids)


def count_signups(conn, event_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM event_signups WHERE event_id = ? AND status = 'available'",
        (event_id,),
    ).fetchone()
    return row[0] if row else 0


def get_allowed_role_ids(conn, event_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT role_id FROM event_allowed_roles WHERE event_id = ?",
        (event_id,),
    ).fetchall()
    return [r[0] for r in rows]


async def insert_schedule(*, interaction, title, category, frequency, interval_value,
                          day_of_week, time_ts, start_ts, end_ts, next_run_at,
                          signup_mode, allowed_role_ids):
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO schedules (
                guild_id, channel_id, creator_id,
                title, category,
                frequency, interval, day_of_week,
                time_of_day, start_date, end_date,
                signup_mode,
                created_at, next_run_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild_id,
                interaction.channel_id,
                interaction.user.id,
                title,
                category,
                frequency,
                interval_value,
                day_of_week,
                time_ts,
                start_ts,
                end_ts,
                signup_mode.lower(),
                now_ts,
                next_run_at,
            ),
        )
        schedule_id = cursor.lastrowid

        if allowed_role_ids:
            for role_id in allowed_role_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO schedule_allowed_roles (schedule_id, role_id) VALUES (?, ?)",
                    (schedule_id, role_id),
                )

        conn.commit()
    finally:
        conn.close()


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
                signup_mode = (row["signup_mode"] or "open").lower()
                max_slots = default_max_slots(row["category"])

                allowed_role_ids = []
                if signup_mode == "role":
                    role_rows = conn.execute(
                        "SELECT role_id FROM schedule_allowed_roles WHERE schedule_id = ?",
                        (row["id"],),
                    ).fetchall()
                    allowed_role_ids = [r[0] for r in role_rows]

                conn.execute(
                    """
                    INSERT INTO events (
                        schedule_id,
                        guild_id, channel_id, creator_id,
                        title, category, signup_mode, max_slots,
                        timestamp, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["guild_id"],
                        row["channel_id"],
                        row["creator_id"],
                        row["title"],
                        row["category"],
                        signup_mode,
                        max_slots,
                        next_run,
                        now_ts
                    ),
                )
                event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                if signup_mode == "role":
                    for role_id in allowed_role_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO event_allowed_roles (event_id, role_id) VALUES (?, ?)",
                            (event_id, role_id),
                        )

                channel = client.get_channel(row["channel_id"])
                if channel is None:
                    channel = await client.fetch_channel(row["channel_id"])

                embed = await build_signup_embed(
                    guild=getattr(channel, "guild", None),
                    title=row["title"],
                    category=row["category"],
                    timestamp=next_run,
                    signup_mode=signup_mode,
                    max_slots=max_slots,
                    creator_id=row["creator_id"],
                    event_id=event_id,
                    allowed_role_ids=allowed_role_ids,
                    schedule_id=row["id"],
                )
                await channel.send(embed=embed, view=SignupView(event_id))

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
        now_ts = int(time.time())
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id FROM events WHERE timestamp > ?",
                (now_ts,),
            ).fetchall()
        finally:
            conn.close()

        for (event_id,) in rows:
            self.add_view(SignupView(event_id))
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
    def __init__(
        self,
        *,
        title: str,
        category: str,
        frequency: str,
        time: str,
        signup_mode: str,
        start_date: str | None,
        end_date: str | None
    ):
        super().__init__(timeout=300)
        self.title = title
        self.category = category
        self.frequency = frequency
        self.time = time
        self.signup_mode = signup_mode
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
        
        time_ts -= time_ts % 60

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
        start_ts -= start_ts % 60

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
        if end_ts is not None:
            end_ts -= end_ts % 60

        if end_ts is not None and end_ts <= start_ts:
            await interaction.response.send_message(
                "end_date must be after start_date.", ephemeral=True
            )
            return

        step_seconds = 86400 if self.frequency == "daily" else 7 * 86400
        step_seconds *= self.interval_value

        first_run_at = time_ts
        while first_run_at < start_ts:
            first_run_at += step_seconds

        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        while first_run_at < now_ts:
            first_run_at += step_seconds

        if self.signup_mode == "Role":
            view = ScheduleRolePickerView(
                title=self.title,
                category=self.category,
                frequency=self.frequency,
                interval_value=self.interval_value,
                day_of_week=self.day_of_week,
                time_ts=time_ts,
                start_ts=start_ts,
                end_ts=end_ts,
                first_run_at=first_run_at,
                creator_id=interaction.user.id,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
            )

            await interaction.response.edit_message(
                content="Select allowed roles (max 5):",
                view=view
            )
            return

        await insert_schedule(
            interaction=interaction,
            title=self.title,
            category=self.category,
            frequency=self.frequency,
            interval_value=self.interval_value,
            day_of_week=self.day_of_week,
            time_ts=time_ts,
            start_ts=start_ts,
            end_ts=end_ts,
            next_run_at=first_run_at,
            signup_mode=self.signup_mode,
            allowed_role_ids=None,
        )
        await interaction.response.edit_message(content="Schedule created.", view=None)




class ScheduleRolePickerView(discord.ui.View):
    def __init__(
        self,
        *,
        title: str,
        category: str,
        frequency: str,
        interval_value: int,
        day_of_week: int | None,
        time_ts: int,
        start_ts: int,
        end_ts: int | None,
        first_run_at: int,
        creator_id: int,
        guild_id: int,
        channel_id: int
    ):
        super().__init__(timeout=300)
        self.title = title
        self.category = category
        self.frequency = frequency
        self.interval_value = interval_value
        self.day_of_week = day_of_week
        self.time_ts = time_ts
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.first_run_at = first_run_at
        self.creator_id = creator_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_role_ids: list[int] = []

    @discord.ui.select(
        placeholder="Select allowed roles (max 5)",
        min_values=1,
        max_values=5,
        cls=discord.ui.RoleSelect,
    )
    async def select_roles(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_ids = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Create Schedule", style=discord.ButtonStyle.green)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role_ids:
            await interaction.response.send_message("Select at least one role.", ephemeral=True)
            return

        await insert_schedule(
            interaction=interaction,
            title=self.title,
            category=self.category,
            frequency=self.frequency,
            interval_value=self.interval_value,
            day_of_week=self.day_of_week,
            time_ts=self.time_ts,
            start_ts=self.start_ts,
            end_ts=self.end_ts,
            next_run_at=self.first_run_at,
            signup_mode="Role",
            allowed_role_ids=self.selected_role_ids,
        )

        await interaction.response.edit_message(content="Schedule created.", view=None)



class EventRolePickerView(discord.ui.View):
    def __init__(
        self,
        *,
        title: str,
        category: str,
        timestamp: int,
        signup_mode: str,
        creator_id: int,
        guild_id: int,
        channel_id: int,
    ):
        super().__init__(timeout=300)
        self.title = title
        self.category = category
        self.timestamp = timestamp
        self.signup_mode = signup_mode
        self.creator_id = creator_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.selected_role_ids: list[int] = []

    @discord.ui.select(
        placeholder="Select allowed roles (max 5)",
        min_values=1,
        max_values=5,
        cls=discord.ui.RoleSelect,
    )
    async def select_roles(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role_ids = [r.id for r in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="Create Event", style=discord.ButtonStyle.green)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role_ids:
            await interaction.response.send_message("Please select at least one role.", ephemeral=True)
            return

        max_slots = default_max_slots(self.category)
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
                    self.guild_id,
                    self.channel_id,
                    self.creator_id,
                    self.title,
                    self.category,
                    self.signup_mode.lower(),
                    max_slots,
                    self.timestamp,
                    now_ts,
                ),
            )
            event_id = cursor.lastrowid

            for role_id in self.selected_role_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO event_allowed_roles (event_id, role_id) VALUES (?, ?)",
                    (event_id, role_id),
                )

            conn.commit()
        finally:
            conn.close()

        embed = await build_signup_embed(
            guild=interaction.guild,
            title=self.title,
            category=self.category,
            timestamp=self.timestamp,
            signup_mode=self.signup_mode,
            max_slots=default_max_slots(self.category),
            creator_id=self.creator_id,
            event_id=event_id,
            allowed_role_ids=self.selected_role_ids,
            schedule_id=None,
        )

        channel = interaction.client.get_channel(self.channel_id)
        if channel is None:
            channel = await interaction.client.fetch_channel(self.channel_id)

        view = SignupView(event_id)
        await channel.send(embed=embed, view=view)
        await interaction.response.edit_message(content="Event created.", view=None)
        

class SignupView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "Sign Up":
                    child.custom_id = f"signup:avail:{event_id}"
                if child.label == "Decline":
                    child.custom_id = f"signup:decline:{event_id}"
                if child.label == "Maybe":
                    child.custom_id = f"signup:maybe:{event_id}"
                    

    async def _set_status(self, interaction: discord.Interaction, status: str):
        conn = get_connection()
        try:
            event = conn.execute(
                "SELECT * FROM events WHERE id = ?",
                (self.event_id,),
            ).fetchone()
            if not event:
                await interaction.response.send_message("Event not found.", ephemeral=True)
                return

            allowed_roles = get_allowed_role_ids(conn, self.event_id)
            signup_mode = (event["signup_mode"] or "open").lower()

            if signup_mode == "invite":
                if interaction.user.id != event["creator_id"]:
                    await interaction.response.send_message("Invite-only. Ask the host.", ephemeral=True)
                    return

            if signup_mode == "role":
                member = interaction.user if isinstance(interaction.user, discord.Member) else None
                if member is None and interaction.guild:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                if not user_has_allowed_role(member, allowed_roles):
                    await interaction.response.send_message("You don't have the required role(s).", ephemeral=True)
                    return

            if status == "available":
                current = conn.execute(
                    "SELECT COUNT(*) FROM event_signups WHERE event_id = ? AND status = 'available'",
                    (self.event_id,),
                ).fetchone()[0]
                max_slots = event["max_slots"]
                if current >= max_slots:
                    await interaction.response.send_message("Event is full.", ephemeral=True)
                    return

            conn.execute(
                """
                INSERT OR REPLACE INTO event_signups (event_id, user_id, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.event_id, interaction.user.id, status, int(datetime.now(tz=timezone.utc).timestamp())),
            )
            conn.commit()
        finally:
            conn.close()

        embed = await build_signup_embed(
            guild=interaction.guild,
            title=event["title"],
            category=event["category"],
            timestamp=event["timestamp"],
            signup_mode=event["signup_mode"],
            max_slots=event["max_slots"],
            creator_id=event["creator_id"],
            event_id=self.event_id,
            allowed_role_ids=allowed_roles,
            schedule_id=event["schedule_id"],
        )

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Sign Up", style=discord.ButtonStyle.green)
    async def signup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_status(interaction, "available")

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_status(interaction, "unavailable")

    @discord.ui.button(label="Maybe", style=discord.ButtonStyle.gray)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_status(interaction, "maybe")


# ============================================================
# Slash commands
# ============================================================

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

client.tree.add_command(create)


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
