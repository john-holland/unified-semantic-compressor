"""High-value incompressible chunks; feed to Cursor call service and improvement loop."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unified_semantic_archiver.db import ContinuumDb


def record_kernel(db: "ContinuumDb", chunk_id: int, source: str, residual: float, status: str = "flagged_research") -> int:
    """Record a kernel that remains incompressible after multiple attempts."""
    return db.unique_kernel_insert(
        chunk_id=chunk_id,
        source_compressor=source,
        residual_metric=residual,
        attempt_count=0,
        status=status,
    )


def get_kernels_for_research(db: "ContinuumDb", status: str = "flagged_research", limit: int = 50) -> list:
    """Get kernels flagged for research (Cursor, improvement feed)."""
    return db.unique_kernel_list(status=status, limit=limit)
