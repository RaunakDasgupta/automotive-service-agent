PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS staff (
  staff_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
  skill TEXT, shift TEXT, team TEXT
);

CREATE TABLE IF NOT EXISTS ros (
  ro_number TEXT PRIMARY KEY,
  vin TEXT NOT NULL, registration TEXT, make TEXT, model TEXT,
  model_year INTEGER, engine TEXT, odometer_miles INTEGER,
  pay_type TEXT, wait_type TEXT,
  checked_in_at TEXT, promised_time TEXT,
  advisor_id TEXT, primary_tech_id TEXT,
  concern TEXT, category TEXT,
  FOREIGN KEY(advisor_id) REFERENCES staff(staff_id)
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, ro_number TEXT NOT NULL, type TEXT NOT NULL,
  at TEXT NOT NULL, actor_id TEXT, shift TEXT, source_update_id TEXT,
  payload TEXT NOT NULL,
  FOREIGN KEY(ro_number) REFERENCES ros(ro_number)
);
CREATE INDEX IF NOT EXISTS idx_events_ro   ON events(ro_number, at);
CREATE INDEX IF NOT EXISTS idx_events_at   ON events(at);

CREATE TABLE IF NOT EXISTS updates (
  update_id TEXT PRIMARY KEY, ro_number TEXT NOT NULL, staff_id TEXT NOT NULL,
  at TEXT NOT NULL, shift TEXT, text TEXT NOT NULL, ground_truth TEXT NOT NULL,
  FOREIGN KEY(ro_number) REFERENCES ros(ro_number)
);
CREATE INDEX IF NOT EXISTS idx_updates_ro    ON updates(ro_number, at);
CREATE INDEX IF NOT EXISTS idx_updates_staff ON updates(staff_id, at);

CREATE TABLE IF NOT EXISTS labour_ops (
  op_code TEXT PRIMARY KEY, description TEXT, flat_rate_hrs REAL,
  category TEXT, min_skill TEXT, safety_critical INTEGER
);
