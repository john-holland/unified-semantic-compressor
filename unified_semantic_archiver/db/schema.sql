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

-- Astral bodies catalog (planets, moons, stars, barycenters)
CREATE TABLE IF NOT EXISTS astral_body_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('planet','moon','star','barycenter')),
    mass_kg REAL,
    radius_m REAL,
    parent_body_id TEXT,
    frame_id TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_astral_body_tenant ON astral_body_catalog(tenant_id);
CREATE INDEX IF NOT EXISTS idx_astral_body_parent ON astral_body_catalog(parent_body_id);
CREATE INDEX IF NOT EXISTS idx_astral_body_kind ON astral_body_catalog(kind);

-- Observer sites (lat/lon/altitude on a body)
CREATE TABLE IF NOT EXISTS astral_observer_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL UNIQUE,
    body_id TEXT NOT NULL,
    lat_deg REAL NOT NULL,
    lon_deg REAL NOT NULL,
    altitude_m REAL DEFAULT 0,
    reference_frame TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_astral_observer_tenant ON astral_observer_sites(tenant_id);
CREATE INDEX IF NOT EXISTS idx_astral_observer_body ON astral_observer_sites(body_id);

-- NASA kernel / flat-file registry
CREATE TABLE IF NOT EXISTS nasa_file_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_type TEXT NOT NULL CHECK (file_type IN ('spk','pck','lsk','fk','horizons')),
    source_url TEXT,
    local_path TEXT NOT NULL,
    checksum TEXT,
    valid_from TEXT,
    valid_to TEXT,
    format_version TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_nasa_file_tenant ON nasa_file_registry(tenant_id);
CREATE INDEX IF NOT EXISTS idx_nasa_file_type ON nasa_file_registry(file_type);

-- Ephemeris samples (ingested position/velocity per body per epoch)
CREATE TABLE IF NOT EXISTS ephemeris_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body_id TEXT NOT NULL,
    epoch_utc TEXT NOT NULL,
    position_x REAL NOT NULL,
    position_y REAL NOT NULL,
    position_z REAL NOT NULL,
    velocity_x REAL,
    velocity_y REAL,
    velocity_z REAL,
    frame_id TEXT,
    source_file_id INTEGER REFERENCES nasa_file_registry(id),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ephemeris_body ON ephemeris_samples(body_id);
CREATE INDEX IF NOT EXISTS idx_ephemeris_epoch ON ephemeris_samples(epoch_utc);
CREATE INDEX IF NOT EXISTS idx_ephemeris_tenant ON ephemeris_samples(tenant_id);

-- Occlusion / eclipse events
CREATE TABLE IF NOT EXISTS occlusion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch_utc TEXT NOT NULL,
    source_body_id TEXT NOT NULL,
    target_body_id TEXT NOT NULL,
    occluder_body_id TEXT NOT NULL,
    occlusion_ratio REAL,
    eclipse_type TEXT CHECK (eclipse_type IN ('partial','annular','total','planet_occludes_planet','planet_occludes_star')),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_occlusion_epoch ON occlusion_events(epoch_utc);
CREATE INDEX IF NOT EXISTS idx_occlusion_tenant ON occlusion_events(tenant_id);

-- Ingestion job tracking
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    payload_json TEXT,
    started_at TEXT,
    finished_at TEXT,
    error_text TEXT,
    attempt_count INTEGER DEFAULT 0,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_tenant ON ingestion_jobs(tenant_id);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_spatial_4d_payload ON spatial_4d(payload_type, payload_id);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_media ON semantic_chunks(media_type);
CREATE INDEX IF NOT EXISTS idx_semantic_chunks_parent ON semantic_chunks(parent_id);
CREATE INDEX IF NOT EXISTS idx_unique_kernels_status ON unique_kernels(status);
CREATE INDEX IF NOT EXISTS idx_unique_kernels_chunk ON unique_kernels(chunk_id);

-- Entropy ring (Entropythief daisy topology)
CREATE TABLE IF NOT EXISTS entropy_ring_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    probe_target TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','mezzed','removed')),
    created_at TEXT DEFAULT (datetime('now')),
    mezzed_at TEXT,
    last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_entropy_ring_nodes_status ON entropy_ring_nodes(status);
CREATE INDEX IF NOT EXISTS idx_entropy_ring_nodes_tenant ON entropy_ring_nodes(tenant_id);

CREATE TABLE IF NOT EXISTS entropy_ring_warehouse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    probe_target TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    retry_count INTEGER DEFAULT 0,
    last_retry TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entropy_warehouse_tenant ON entropy_ring_warehouse(tenant_id);

CREATE TABLE IF NOT EXISTS entropy_node_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL CHECK (event IN ('added','removed','mezzed','refreshed')),
    node_id TEXT NOT NULL,
    ts TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entropy_node_events_node ON entropy_node_events(node_id);
CREATE INDEX IF NOT EXISTS idx_entropy_node_events_ts ON entropy_node_events(ts);

CREATE TABLE IF NOT EXISTS entropy_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL UNIQUE,
    earned INTEGER NOT NULL DEFAULT 0,
    spent INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entropy_credits_tenant ON entropy_credits(tenant_id);
