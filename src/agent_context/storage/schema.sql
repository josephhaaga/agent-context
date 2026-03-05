-- agent-context SQLite schema
-- Uses FTS5 for full-text search and a separate embeddings table for semantic search.

-- Main documents table
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,          -- '{source}:{source_id}'
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    url         TEXT,
    author      TEXT,
    created_at  TEXT,                      -- ISO 8601
    updated_at  TEXT,
    metadata    TEXT,                      -- JSON blob
    indexed_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_source      ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at  ON documents(updated_at);

-- FTS5 virtual table (content= keeps documents as the source of truth,
-- triggers below keep them in sync)
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    content,
    content='documents',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS index in sync with documents table
CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
    INSERT INTO documents_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

-- Embeddings table for semantic search
CREATE TABLE IF NOT EXISTS embeddings (
    document_id TEXT PRIMARY KEY,          -- matches documents.id
    embedding   BLOB NOT NULL,             -- numpy float32 array serialized with numpy.save
    model       TEXT NOT NULL,             -- e.g. 'all-MiniLM-L6-v2'
    created_at  TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Source index metadata (tracks last successful index per source)
CREATE TABLE IF NOT EXISTS source_meta (
    source          TEXT PRIMARY KEY,
    last_indexed    TEXT,                  -- ISO 8601 timestamp
    document_count  INTEGER DEFAULT 0,
    last_error      TEXT
);
