CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER NOT NULL,
  channel_id INTEGER NOT NULL,
  creator_id INTEGER NOT NULL,
  title TEXT,
  category TEXT NOT NULL,

  frequency TEXT NOT NULL,
  interval INTEGER NOT NULL,

  day_of_week INTEGER,

  time_of_day TEXT NOT NULL,
  next_run_at INTEGER,
  start_date TEXT NOT NULL,
  end_date TEXT,

  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedules_guild_id ON schedules(guild_id);
CREATE INDEX IF NOT EXISTS idx_schedules_category ON schedules(category);