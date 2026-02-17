# Schema ownership and evolution

## Where the schema lives

All continuum tables, including **library_documents** (used by the continuum library server), are defined in **USC** (unified-semantic-compressor):

- **Single source of truth:** `unified_semantic_archiver/db/schema.sql`
- **Initialization:** `init_schema()` in `continuum_db.py` runs this SQL when opening the DB. The continuum app does not own a separate schema file; it uses this one via `ContinuumDb`.

So the continuum **app** (Flask server) and Unity/CLI all use the same SQLite DB and the same schema. There are no “continuum-only” tables; they live in USC and are shared.

## Evolving the schema

- **New tables or columns** that the continuum server or CLI need should be added to USC’s `schema.sql` (and to `ContinuumDb` and CLI as needed). For existing DBs, add one-off migration steps (e.g. `ALTER TABLE`) and document them in `db/` (see `MIGRATION_tenant_id.md`).
- **No versioned migrations** (e.g. Flyway/Alembic) are in use; schema changes are applied by re-running init on a new DB or by manual ALTER + docs.
- If continuum ever needs tables that USC should not own, options are: (1) add a second SQLite file and attach it, or (2) add a separate schema file and migration story in the continuum repo. For now, the decision is: **continuum app tables live in USC and are shared.**
