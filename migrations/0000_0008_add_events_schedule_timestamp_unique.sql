CREATE UNIQUE INDEX IF NOT EXISTS idx_events_schedule_ts
ON events(schedule_id, timestamp);