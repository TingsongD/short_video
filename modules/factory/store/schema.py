"""Ordered migrations. Every DB carries meta.schema_version; an older
binary refuses a newer database rather than reinterpreting it."""

CURRENT_VERSION = 9

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
  WHERE status IN ('prepared','dispatching','accepted','running',
                   'unknown','cancel_requested');

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
    (6, """
ALTER TABLE attempts ADD COLUMN retry_state TEXT NOT NULL DEFAULT '{}';
"""),
    (7, """
CREATE TABLE discovery_cache (
  query_key TEXT NOT NULL,
  page INTEGER NOT NULL,
  body TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  run_id TEXT NOT NULL,
  PRIMARY KEY (query_key, page)
);
"""),
    (8, """
CREATE TABLE migration_issues (
  kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
  reason TEXT NOT NULL, original_body TEXT NOT NULL,
  resolved_evidence TEXT, PRIMARY KEY(kind,id,revision,reason)
);
INSERT INTO migration_issues(kind,id,revision,reason,original_body)
SELECT kind,id,revision,'revision_body_mismatch',body FROM records
WHERE kind IN ('composition','experimentrevision')
AND COALESCE(json_extract(body,'$.revision'),revision) != revision;
INSERT OR IGNORE INTO migration_issues(kind,id,revision,reason,original_body)
SELECT kind,id,revision,'legacy_draft_requires_review',body FROM records
WHERE kind IN ('experimentdraft','experiment_draft');
DROP INDEX records_hash;
CREATE INDEX records_hash ON records(kind,content_hash)
WHERE content_hash IS NOT NULL;
UPDATE records SET revision=COALESCE(json_extract(body,'$.experiment_revision'),1),
body=json_set(body,'$.revision',COALESCE(json_extract(body,'$.experiment_revision'),1))
WHERE kind='variantplan' AND revision=0;
"""),
    (9, """
CREATE TABLE effect_bindings (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), authorization_id TEXT NOT NULL,
 operation_key TEXT NOT NULL, price_id TEXT, worker_id TEXT NOT NULL,
 fencing INTEGER NOT NULL, UNIQUE(authorization_id,operation_key)
);
CREATE TABLE remote_holds (
 attempt_id TEXT PRIMARY KEY REFERENCES attempts(id), job_id TEXT NOT NULL,
 capacity TEXT NOT NULL, created_at TEXT NOT NULL
);
ALTER TABLE jobs ADD COLUMN next_attempt_at TEXT;
ALTER TABLE jobs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
"""),
]
