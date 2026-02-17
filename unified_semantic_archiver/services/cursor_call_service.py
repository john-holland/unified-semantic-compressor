"""
Cursor-based call service: package research context, invoke Cursor for model updates and improvements.
Persists suggestions to research_suggestions table.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger("unified_semantic_archiver.cursor_call_service")


def build_context(db_path: Path) -> dict:
    """Build research context for Cursor (unique kernels, runs, chunks)."""
    from unified_semantic_archiver.research.improvement_feed import build_improvement_context
    return build_improvement_context(Path(db_path))


def persist_suggestion(db_path: Path, source: str, recommendation_text: str, context_json: str | None = None) -> int:
    """Persist a suggestion from Cursor or manual input to research_suggestions."""
    from unified_semantic_archiver.db import ContinuumDb
    db = ContinuumDb(db_path)
    return db.research_suggestion_insert(
        source=source,
        recommendation_text=recommendation_text,
        context_json=context_json,
        status="pending",
    )


def invoke_cursor_workflow(
    db_path: Path,
    *,
    context_output_path: Path | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """
    Package context, optionally invoke Cursor.
    Writes context to JSON file; if cursor CLI available, can trigger agent.
    Returns dict with context_path, suggestion_count.
    """
    cb = progress_callback or (lambda _p, _v, _m: None)
    cb("build", 0.2, "Building research context…")
    ctx = build_context(db_path)
    out_path = context_output_path or Path(db_path).parent / "cursor_research_context.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=2)
    cb("context", 0.5, f"Context written to {out_path}")

    # Stub: try to invoke cursor if available (cursor --agent or similar)
    # Cursor IDE may not expose CLI; document manual workflow
    cb("cursor", 0.7, "Cursor invocation (stub): paste context into Cursor Rules or agent.")
    log.info("Context saved to %s. To use Cursor: open this file, paste into Cursor Rules or agent, request algorithm/model improvements.", out_path)

    return {"context_path": str(out_path), "kernel_count": len(ctx.get("unique_kernels", []))}
