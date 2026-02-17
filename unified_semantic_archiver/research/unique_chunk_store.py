"""Persist chunks that resist compression; feed to research/improvement loop."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unified_semantic_archiver.db import ContinuumDb


def add_unique_chunk(db: "ContinuumDb", chunk_id: int, source_compressor: str, residual_metric: float = 1.0) -> int:
    """Record a chunk that resisted compression; returns unique_kernel id."""
    return db.unique_kernel_insert(
        chunk_id=chunk_id,
        source_compressor=source_compressor,
        residual_metric=residual_metric,
        status="pending",
    )


def get_pending_kernels(db: "ContinuumDb", limit: int = 100) -> list:
    """Get pending unique kernels for data compressor or research feed."""
    return db.unique_kernel_list(status="pending", limit=limit)
