# Migration: add tenant_id to library_documents

For **existing** continuum databases created before `tenant_id` was added to the schema:

1. Backup your database.
2. Run the following SQL (SQLite):

```sql
ALTER TABLE library_documents ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_library_documents_tenant_id ON library_documents(tenant_id);
```

New databases created with `init_schema()` (or `python -m unified_semantic_archiver init --db ./continuum.db`) already include `tenant_id` in the table definition.
