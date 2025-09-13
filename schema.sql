-- Schema for Local Responses API skeleton

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    token_count INTEGER DEFAULT 0,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON messages(thread_id, created_at);

CREATE TABLE IF NOT EXISTS responses (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    request_message_id TEXT,
    response_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    usage_json TEXT,
    error_text TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_responses_thread_created ON responses(thread_id, created_at);

CREATE TABLE IF NOT EXISTS summaries (
    thread_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name);
