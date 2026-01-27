CREATE TABLE IF NOT EXISTS schedule_allowed_roles (
  schedule_id INTEGER NOT NULL,
  role_id INTEGER NOT NULL,
  PRIMARY KEY (schedule_id, role_id),
  FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schedule_allowed_roles_schedule_id
  ON schedule_allowed_roles(schedule_id);

CREATE INDEX IF NOT EXISTS idx_schedule_allowed_roles_role_id
  ON schedule_allowed_roles(role_id);
