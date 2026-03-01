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

USC now exposes media parity primitives via `unified_semantic_archiver.media.UscMediaService` (store/reconstitute/diff/stream/settings/cache/T2V download surface). The implementation currently wraps `video_storage_tool` runtime components where applicable while providing a stable USC callable contract for Continuum. See [docs/VIDEO_PIPELINE.md](docs/VIDEO_PIPELINE.md).

Minimization now uses an ETL adapter pattern (`extract -> tokenize -> bucket -> score -> select -> persist`) and can be enabled/configured through `minimization.*` media settings. Adapter cohorts include `default`, `cairn_audio_v1`, `cairn_residual_v1`, `planar_hyperplane_v1`, and `audio_captioning_v1`, with JSON-first model loading and optional sklearn/joblib support.

V2 introduces per-adapter requirement contracts and runtime fallback routing, plus transcript/audio-captioning policies for stronger speech + SFX coverage.

## Entropy Policy References

USC remains the primary home for semantic/validation architecture. The current operational compliance gate for entropy claim wording and live probe evidence is documented in:

- [docs/ENTROPY_POLICY_LINKS.md](docs/ENTROPY_POLICY_LINKS.md)

## Structure

- `unified_semantic_archiver/db/` — Schema + ContinuumDb micro ORM
- `unified_semantic_archiver/etl/` — Luigi ETL (identity stub)
- `unified_semantic_archiver/compressors/` — Video, audio, library, data; ring orchestrator
- `unified_semantic_archiver/research/` — Unique chunk/kernel store; improvement feed
- `unified_semantic_archiver/services/` — Cursor call service
- `unified_semantic_archiver/cli/` — Query DB (used by Unity Explorer)
