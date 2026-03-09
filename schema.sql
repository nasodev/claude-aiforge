CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL CHECK (type IN ('jira', 'schedule')),
    description TEXT,
    enabled     INTEGER DEFAULT 1,
    jira_project TEXT,
    jira_label   TEXT,
    jira_status  TEXT,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS schedules (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT,
    cron_expr       TEXT NOT NULL,
    work_dir        TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    enabled         INTEGER DEFAULT 1,
    status          TEXT DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'paused', 'error')),
    last_run_at     TEXT,
    next_run_at     TEXT,
    run_count       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS executions (
    id               TEXT PRIMARY KEY,
    schedule_id      TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
    pid              INTEGER,
    status           TEXT DEFAULT 'running' CHECK (status IN ('running', 'success', 'error', 'timeout', 'killed')),
    command          TEXT NOT NULL,
    work_dir         TEXT,
    log_path         TEXT,
    issue_key        TEXT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    duration_seconds INTEGER,
    result_summary   TEXT,
    error_message    TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_schedules_project ON schedules(project_id);
CREATE INDEX IF NOT EXISTS idx_executions_schedule ON executions(schedule_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_started ON executions(started_at);
