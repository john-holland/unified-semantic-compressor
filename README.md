# Unified Semantic Compressor (USC)

Flowering ring of semantic compressors (video, audio, library, data) with continuum DB, ETL, and research feed. This repo is **USC** (Unified Semantic Compressor); the Python package and import name is **unified_semantic_archiver** (USA). In prose we use “USC” for the repo/package; use the import name only in code. The **continuum** repo provides the library server (web UI + API).

## Install

```bash
pip install -e .
# or: pip install -r requirements.txt
```

## Usage

```bash
# Initialize continuum DB
python -m unified_semantic_archiver init --db ./continuum.db

# Run ETL (Luigi)
python -m unified_semantic_archiver run-etl --source ./input/ --db ./continuum.db

# Compress media
python -m unified_semantic_archiver compress --media video.mp4 --type video --out ./out --db ./continuum.db

# Build Cursor research context
python -m unified_semantic_archiver cursor-research --db ./continuum.db --output ./context.json

# Query DB (e.g. for Unity Explorer)
python -m unified_semantic_archiver.cli.query_db --db ./continuum.db --table library_documents
```

## Tests

Run: `pytest tests/` (requires `pip install -e ".[dev]"` or `pip install pytest`). Smoke tests cover `library_document_insert` and `library_document_search` with tenant scoping.

## Continuum app

The **continuum** repository uses this package and provides the library server (upload, search, map). Install continuum and run its server; it depends on `unified-semantic-compressor`.

## Schema ownership

Continuum tables (including `library_documents`) live in USC. The **continuum** app has no separate schema; it uses `ContinuumDb` and this schema. See [unified_semantic_archiver/db/SCHEMA_OWNERSHIP.md](unified_semantic_archiver/db/SCHEMA_OWNERSHIP.md) for how to evolve the schema and handle migrations.

## Full video pipeline

The video compressor uses **video_storage_tool** for the full pipeline (describe, diff, script-to-video). That package is not part of USC; it currently lives in **Drawer 2** (`Scripts/video_storage_tool/`). Without it, the video compressor runs a stub. See [docs/VIDEO_PIPELINE.md](docs/VIDEO_PIPELINE.md).

## Structure

- `unified_semantic_archiver/db/` — Schema + ContinuumDb micro ORM
- `unified_semantic_archiver/etl/` — Luigi ETL (identity stub)
- `unified_semantic_archiver/compressors/` — Video, audio, library, data; ring orchestrator
- `unified_semantic_archiver/research/` — Unique chunk/kernel store; improvement feed
- `unified_semantic_archiver/services/` — Cursor call service
- `unified_semantic_archiver/cli/` — Query DB (used by Unity Explorer)
