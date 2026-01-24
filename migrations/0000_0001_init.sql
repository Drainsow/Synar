CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER NOT NULL,
  channel_id INTEGER NOT NULL,
  creator_id INTEGER NOT NULL,
  title TEXT,
  timestamp INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_guild_id ON events(guild_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);