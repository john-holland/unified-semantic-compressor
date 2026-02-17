"""
Video compressor: chunk (3x3, 4x4), describe (visual AST), generate proximal, diff, minimize toward unique chunks.
Extends video_storage_tool; stores altered script + diff in continuum DB.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

log = logging.getLogger("unified_semantic_archiver.video_compressor")

# Add video_storage_tool to path
_scripts = Path(__file__).resolve().parent.parent.parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))


def video_compress(
    video_path: Path,
    out_dir: Path,
    *,
    grid_size: int = 4,
    db_path: Path | None = None,
    config: dict | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """
    Compress video: chunk -> describe -> generate -> diff -> minimize -> store.
    Uses video_storage_tool for describe (Whisper + visual) and diff.
    Returns dict with chunk_keys, script_path, diff_path, unique_chunk_refs.
    """
    config = config or {}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cb = progress_callback or (lambda _p, _v, _m: None)

    try:
        from video_storage_tool.video_to_script import video_to_script
        from video_storage_tool.diff import compute_diff
        from video_storage_tool.script_to_video import script_to_video
        from video_storage_tool.audio import extract_and_compress_audio
    except ImportError as e:
        log.warning("video_storage_tool not available: %s. Using stub.", e)
        return _stub_compress(video_path, out_dir, grid_size, db_path, cb)

    # Step 1: extract audio
    cb("extracting_audio", 0.1, "Extracting audio…")
    audio_path = out_dir / "audio.aac"
    if not audio_path.exists():
        audio_cfg = config.get("audio", {})
        audio_path = extract_and_compress_audio(
            video_path,
            out_dir,
            format=audio_cfg.get("format", "aac"),
            max_mb=audio_cfg.get("max_mb", 5.0),
            ffmpeg_path=audio_cfg.get("ffmpeg_path"),
        )

    # Step 2: describe (script = transcript + visual)
    cb("describing", 0.25, "Video to script…")
    script_path = out_dir / "script.txt"
    if not script_path.exists():
        script_path = video_to_script(
            video_path,
            audio_path,
            out_dir,
            backend=config.get("script", {}).get("backend", "whisper"),
            config=config,
            progress_callback=progress_callback,
        )

    # Step 3: generate proximal (script -> resultant video)
    cb("generating", 0.5, "Script to resultant video…")
    resultant_path = out_dir / "resultant.mp4"
    if not resultant_path.exists():
        t2v_cfg = config.get("t2v", {})
        script_to_video(
            script_path,
            out_dir,
            backend=t2v_cfg.get("backend", "stub"),
            model_path=t2v_cfg.get("model_path"),
            model_id=t2v_cfg.get("model_id"),
            config=t2v_cfg,
            progress_callback=progress_callback,
            ffmpeg_path=config.get("audio", {}).get("ffmpeg_path"),
        )
        resultant_path = out_dir / "resultant.mp4"

    # Step 4: diff (original - resultant)
    cb("diffing", 0.7, "Computing diff…")
    diff_path = compute_diff(
        video_path,
        resultant_path,
        out_dir,
        enabled=True,
        quality=config.get("diff", {}).get("quality", 6),
        ffmpeg_path=config.get("audio", {}).get("ffmpeg_path"),
    )

    # Step 5: minimize (stub: identify unique chunks from high-residual regions)
    cb("minimizing", 0.85, "Minimizing toward unique chunks…")
    unique_refs = _minimize_stub(out_dir, script_path, grid_size)

    # Step 6: store in continuum DB
    if db_path:
        _store_to_db(db_path, video_path, script_path, diff_path, unique_refs, "video")

    cb("done", 1.0, "Video compression complete.")
    return {
        "script_path": str(script_path),
        "resultant_path": str(resultant_path),
        "diff_path": str(diff_path) if diff_path else None,
        "unique_chunk_refs": unique_refs,
    }


def _minimize_stub(out_dir: Path, script_path: Path, grid_size: int) -> list[str]:
    """Stub: return empty list; real impl would regress description toward unique chunks."""
    return []


def _store_to_db(
    db_path: Path,
    source_path: Path,
    script_path: Path,
    diff_path: Path | None,
    unique_refs: list[str],
    media_type: str,
) -> None:
    from unified_semantic_archiver.db import ContinuumDb

    db = ContinuumDb(db_path)
    script_text = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    chunk_id = db.semantic_chunk_insert(
        media_type=media_type,
        chunk_key=source_path.name,
        description_text=script_text[:50000],
        diff_blob_ref=str(diff_path) if diff_path else None,
    )
    for ref in unique_refs:
        db.unique_kernel_insert(chunk_id=chunk_id, source_compressor="video", status="pending")


def _stub_compress(
    video_path: Path,
    out_dir: Path,
    grid_size: int,
    db_path: Path | None,
    cb: Callable[[str, float, str], None],
) -> dict:
    """Fallback when video_storage_tool not available."""
    cb("stub", 1.0, "Video compressor stub (install video_storage_tool for full pipeline).")
    script_path = out_dir / "script.txt"
    script_path.write_text(f"[Stub: {video_path.name}]", encoding="utf-8")
    if db_path:
        _store_to_db(db_path, video_path, script_path, None, [], "video")
    return {"script_path": str(script_path), "resultant_path": None, "diff_path": None, "unique_chunk_refs": []}


def image_compress(
    image_path: Path,
    out_dir: Path,
    *,
    db_path: Path | None = None,
    config: dict | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """Image compressor: same pipeline as video but single frame. (Plan 3.1.1)"""
    # Treat single image as 1-frame video; reuse video_compress with grid_size=1
    return video_compress(
        image_path,
        out_dir,
        grid_size=1,
        db_path=db_path,
        config=config,
        progress_callback=progress_callback,
    )
