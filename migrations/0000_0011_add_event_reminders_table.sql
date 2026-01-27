CREATE TABLE IF NOT EXISTS event_reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  remind_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(event_id, user_id, remind_at)
);

CREATE INDEX IF NOT EXISTS idx_event_reminders_remind_at
  ON event_reminders(remind_at);