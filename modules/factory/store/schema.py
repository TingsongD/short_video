"""Ordered migrations. Every DB carries meta.schema_version; an older
binary refuses a newer database rather than reinterpreting it."""

CURRENT_VERSION = 5

MIGRATIONS = [
    (1, """
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE records (
  kind TEXT NOT NULL,
  id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  schema_version TEXT NOT NULL,
  status TEXT NOT NULL,
  parent_hash TEXT,
  content_hash TEXT,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (kind, id, revision)
);
CREATE UNIQUE INDEX records_hash ON records(kind, content_hash)
  WHERE content_hash IS NOT NULL;

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  logical_key TEXT NOT NULL UNIQUE,
  phase TEXT NOT NULL,
  experiment_id TEXT,
  revision INTEGER,
  variant_key TEXT,
  status TEXT NOT NULL,
  depends_on TEXT NOT NULL DEFAULT '[]',
  retry_class TEXT NOT NULL DEFAULT 'none',
  lease_owner TEXT,
  lease_expires TEXT,
  fencing_token INTEGER NOT NULL DEFAULT 0,
  blocked_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX jobs_ready ON jobs(status, phase);

CREATE TABLE attempts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  attempt_seq INTEGER NOT NULL,
  request_hash TEXT,
  remote_id TEXT,
  status TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (job_id, attempt_seq)
);
CREATE INDEX attempts_remote ON attempts(remote_id) WHERE remote_id IS NOT NULL;
CREATE INDEX attempts_unfinished ON attempts(status)
  WHERE status IN ('dispatching','accepted','running','unknown');

CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  stream TEXT NOT NULL,
  type TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX events_stream ON events(stream, seq);

CREATE TABLE outbox (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  intent_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  dispatched_at TEXT
);
CREATE INDEX outbox_pending ON outbox(status) WHERE status = 'pending';
"""),
    (2, """
CREATE TABLE intents (
  intent_key TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  reservation_id TEXT,
  remote_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (request_hash, kind)
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  sha256 TEXT,
  kind TEXT,
  byte_count INTEGER,
  probe TEXT,
  provenance TEXT,
  local_path TEXT,
  status TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX artifacts_sha ON artifacts(sha256);
"""),
    (3, """
CREATE TABLE artifact_links (
  artifact_id TEXT NOT NULL,
  owner_kind TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (artifact_id, owner_kind, owner_id)
);

CREATE TABLE artifact_sources (
  artifact_id TEXT NOT NULL,
  source_key TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (artifact_id, source_key)
);
"""),
    (4, """
CREATE TABLE budgets (
  id TEXT PRIMARY KEY,
  unit TEXT NOT NULL,
  scope TEXT NOT NULL,
  scope_key TEXT NOT NULL DEFAULT '',
  cap_amount INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE reservations (
  id TEXT PRIMARY KEY,
  authorization_id TEXT,
  request_hash TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  settled_at TEXT,
  evidence TEXT
);
CREATE UNIQUE INDEX reservations_request ON reservations(request_hash)
  WHERE request_hash IS NOT NULL;

CREATE TABLE reservation_lines (
  reservation_id TEXT NOT NULL REFERENCES reservations(id),
  budget_id TEXT NOT NULL REFERENCES budgets(id),
  amount INTEGER NOT NULL,
  settled_amount INTEGER,
  kind TEXT,
  PRIMARY KEY (reservation_id, budget_id)
);

CREATE TABLE ledger_imports (
  import_key TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  body TEXT NOT NULL,
  imported_at TEXT NOT NULL
);
"""),
    (5, """
CREATE TABLE capacities (
  name TEXT PRIMARY KEY,
  limit_n INTEGER NOT NULL
);

CREATE TABLE capacity_holds (
  capacity TEXT NOT NULL,
  job_id TEXT NOT NULL,
  holder TEXT NOT NULL,
  fencing INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  retained_reason TEXT,
  PRIMARY KEY (capacity, job_id)
);
CREATE INDEX holds_expiry ON capacity_holds(expires_at);

CREATE TABLE scheduler_flags (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""),
]
