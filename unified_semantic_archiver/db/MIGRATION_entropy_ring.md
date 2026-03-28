# Migration: Entropy Ring Tables

For existing continuum databases created before this migration, run the entropy table SQL from `schema.sql` (the `CREATE TABLE IF NOT EXISTS` block for `entropy_ring_nodes`, `entropy_ring_warehouse`, `entropy_node_events`, `entropy_credits`).

Alternatively, re-run `python -m unified_semantic_archiver init --db ./continuum.db` which applies the full schema; `IF NOT EXISTS` ensures no conflicts.
