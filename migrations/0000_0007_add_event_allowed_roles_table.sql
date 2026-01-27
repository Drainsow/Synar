CREATE TABLE IF NOT EXISTS event_allowed_roles (
    event_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (event_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_event_allowed_roles_event_id
    ON event_allowed_roles(event_id);
    
CREATE INDEX IF NOT EXISTS idx_event_allowed_roles_role_id
    ON event_allowed_roles(role_id);