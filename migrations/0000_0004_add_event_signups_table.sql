CREATE TABLE IF NOT EXISTS event_signups (
    event_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'available',
    created_at INTEGER NOT NULL,
    PRIMARY KEY (event_id, user_id)
);