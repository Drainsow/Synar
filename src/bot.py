import logging
import time
from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import tasks

from config import ENV, DISCORD_TOKEN, DEV_GUILD_ID, LOG_LEVEL
from storage.db import init_db, get_connection
from helpers import default_max_slots
from embeds import build_signup_embed
from views import SignupView
from commands import register_commands



class MyClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        register_commands(self)
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


client = MyClient()


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



def setup_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


log = logging.getLogger("synar")


def main() -> None:
    setup_logging()
    init_db()
    log.info("Starting Synar (env=%s)", ENV)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()