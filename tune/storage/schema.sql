PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS builds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  fc_snapshot_json TEXT NOT NULL DEFAULT '{}',
  operator_notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loops (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  build_id INTEGER NOT NULL REFERENCES builds(id),
  tune_goal TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS blackbox_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  build_id INTEGER NOT NULL REFERENCES builds(id),
  source_path TEXT NOT NULL,
  managed_path TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  size_bytes INTEGER NOT NULL,
  parse_status TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tuning_iterations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  loop_id INTEGER NOT NULL REFERENCES loops(id),
  status TEXT NOT NULL DEFAULT 'open',
  failure_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS iteration_logs (
  iteration_id INTEGER NOT NULL REFERENCES tuning_iterations(id),
  log_id INTEGER NOT NULL REFERENCES blackbox_logs(id),
  role TEXT NOT NULL DEFAULT 'selected',
  PRIMARY KEY (iteration_id, log_id)
);

CREATE TABLE IF NOT EXISTS diagnoses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  iteration_id INTEGER NOT NULL UNIQUE REFERENCES tuning_iterations(id),
  body TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tune_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  iteration_id INTEGER NOT NULL UNIQUE REFERENCES tuning_iterations(id),
  build_id INTEGER NOT NULL REFERENCES builds(id),
  status TEXT NOT NULL DEFAULT 'proposed',
  settings_json TEXT NOT NULL,
  cli_text TEXT NOT NULL DEFAULT '',
  rejection_reason TEXT,
  application_failure TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at TEXT
);


CREATE TABLE IF NOT EXISTS operator_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT
);


CREATE TABLE IF NOT EXISTS decoded_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_id INTEGER NOT NULL REFERENCES blackbox_logs(id),
  csv_path TEXT NOT NULL,
  decoder_command TEXT NOT NULL DEFAULT 'blackbox_decode',
  decoded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_id INTEGER NOT NULL REFERENCES blackbox_logs(id),
  analysis_json TEXT NOT NULL,
  analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
