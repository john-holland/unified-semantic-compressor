-- Unified Semantic Archiver continuum database schema
-- SQLite; run once to initialize

-- Key-value metadata
CREATE TABLE IF NOT EXISTS continuum_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Mirrors SpatialGenerator4D volumes (x,y,z,t bounds)
CREATE TABLE IF NOT EXISTS spatial_4d (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bounds4_json TEXT NOT NULL,
    payload_type TEXT,
    payload_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Document blobs (tar hash, path)
CREATE TABLE IF NOT EXISTS document_blobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tar_hash TEXT NOT NULL,
    path TEXT NOT NULL,
    mime_type TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Semantic chunks from compressors
CREATE TABLE IF NOT EXISTS semantic_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT NOT NULL CHECK (media_type IN ('audio','video','library','image','data')),
    chunk_key TEXT NOT NULL,
    description_text TEXT,
    diff_blob_ref TEXT,
    parent_id INTEGER REFERENCES semantic_chunks(id),
    quad_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Unique kernels (chunks that resist compression)
CREATE TABLE IF NOT EXISTS unique_kernels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id INTEGER REFERENCES semantic_chunks(id),
    source_compressor TEXT NOT NULL,
    residual_metric REAL,
    attempt_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','compressed','flagged_research')),
    created_at TEXT DEFAULT (datetime('now'))
);

-- Compression run history
CREATE TABLE IF NOT EXISTS compression_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER,
    strategy TEXT NOT NULL,
    config_json TEXT,
    output_hash TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Research suggestions (from Cursor, manual, etc.)
CREATE TABLE IF NOT EXISTS research_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('cursor','manual')),
    context_json TEXT,
    recommendation_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Library documents (upload/download, search by location and type)
-- tenant_id: scope per game/team; use 'default' for local dev (see TENANT.md / CONTINUUM_AND_COMPRESSOR.md).
CREATE TABLE IF NOT EXISTS library_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type TEXT NOT NULL CHECK (document_type IN ('video','document','audio','image','program','data')),
    blob_ref TEXT,
    url TEXT,
    type_metadata TEXT,
    owner_id TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    lat REAL,
    lon REAL,
    altitude_m REAL,
    geohash TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_library_documents_type ON library_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_library_documents_geohash ON library_documents(geohash);
CREATE INDEX IF NOT EXISTS idx_library_documents_owner ON library_documents(owner_id);
CREATE INDEX IF NOT EXISTS idx_library_documents_tenant_id ON library_documents(tenant_id);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_spatial_4d_payload ON spatial_4d(payload_type, payload_id);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_media ON semantic_chunks(media_type);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_parent ON semantic_chunks(parent_id);
CREATE INDEX IF NOT EXISTS idx_unique_kernels_status ON unique_kernels(status);
CREATE INDEX IF NOT EXISTS idx_unique_kernels_chunk ON unique_kernels(chunk_id);
