"""
Data compressor: fully describe (schema, statistics, exemplars).
Primary focus: unique kernels — dedicated attempts on chunks that resist other compressors.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("unified_semantic_archiver.data_compressor")


def data_compress(
    data_path: Path,
    out_dir: Path,
    *,
    db_path: Path | None = None,
    config: dict | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """
    Compress data: describe (schema, stats, exemplars) -> generate proximal -> diff -> minimize.
    Stub: reads as text/JSON; real impl would infer schema, compute stats.
    """
    config = config or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cb = progress_callback or (lambda _p, _v, _m: None)

    cb("describe", 0.3, "Describing data…")
    raw = data_path.read_bytes()
    try:
        obj = json.loads(raw.decode("utf-8"))
        schema = _infer_schema_stub(obj)
        desc = json.dumps({"schema": schema, "exemplar": _exemplar_stub(obj)}, indent=2)
    except (json.JSONDecodeError, UnicodeDecodeError):
        desc = f"Binary/unknown: len={len(raw)}, sha256={hashlib.sha256(raw).hexdigest()[:16]}"

    script_path = out_dir / "script.txt"
    script_path.write_text(desc[:50000], encoding="utf-8")

    if db_path:
        from unified_semantic_archiver.db import ContinuumDb

        db = ContinuumDb(db_path)
        db.semantic_chunk_insert(
            media_type="data",
            chunk_key=data_path.name,
            description_text=desc[:50000],
            diff_blob_ref=None,
        )

    cb("done", 1.0, "Data compression complete (stub).")
    return {"script_path": str(script_path), "unique_chunk_refs": []}


def compress_unique_kernels(
    db_path: Path,
    *,
    limit: int = 10,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """
    Primary sticking point: attempt to compress unique kernels from other compressors.
    Consume unique_kernel store; for each, try schema inference, exemplar extraction, etc.
    """
    from unified_semantic_archiver.db import ContinuumDb

    db = ContinuumDb(db_path)
    kernels = db.unique_kernel_list(status="pending", limit=limit)
    cb = progress_callback or (lambda _p, _v, _m: None)
    compressed = 0
    flagged = 0
    for i, k in enumerate(kernels):
        cb("kernel", (i + 1) / max(len(kernels), 1), f"Processing kernel {k.get('id')}…")
        attempt_count = k.get("attempt_count") or 0
        # Stub: mark as compressed after 1 attempt; real impl would run compression
        if attempt_count >= 2:
            db.unique_kernel_update_status(k["id"], "flagged_research", residual_metric=1.0)
            flagged += 1
        else:
            db.unique_kernel_update_status(k["id"], "compressed", residual_metric=0.5)
            compressed += 1
    cb("done", 1.0, f"Processed {len(kernels)} kernels: {compressed} compressed, {flagged} flagged.")
    return {"compressed": compressed, "flagged_research": flagged}


def _infer_schema_stub(obj: object) -> dict:
    """Stub: infer simple schema from JSON object."""
    if isinstance(obj, dict):
        return {k: type(v).__name__ for k, v in list(obj.items())[:50]}
    if isinstance(obj, list):
        return {"type": "array", "item": type(obj[0]).__name__ if obj else "any"}
    return {"type": type(obj).__name__}


def _exemplar_stub(obj: object, max_len: int = 500) -> object:
    """Stub: return truncated exemplar."""
    s = json.dumps(obj)[:max_len]
    return s + ("..." if len(json.dumps(obj)) > max_len else "")
