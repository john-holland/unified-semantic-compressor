"""Feed unique chunks to AI/ML pipelines for compressor improvement."""

from pathlib import Path
from typing import Callable

from unified_semantic_archiver.db import ContinuumDb
from .unique_kernel_store import get_kernels_for_research


def build_improvement_context(db_path: Path, limit: int = 20) -> dict:
    """Build context dict for Cursor or improvement pipeline."""
    db = ContinuumDb(db_path)
    kernels = get_kernels_for_research(db, status="flagged_research", limit=limit)
    chunks = []
    for k in kernels:
        chunk_id = k.get("chunk_id")
        if chunk_id:
            rows = db.execute_read("SELECT * FROM semantic_chunks WHERE id = ?", (chunk_id,))
            if rows:
                chunks.append({"kernel": k, "chunk": rows[0]})
    runs = db.compression_run_list(limit=10)
    return {
        "unique_kernels": kernels,
        "chunks_with_kernels": chunks,
        "recent_runs": runs,
    }
