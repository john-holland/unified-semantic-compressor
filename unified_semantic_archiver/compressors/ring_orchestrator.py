"""
Flowering ring orchestrator: Video -> Audio -> Library -> Data -> Video.
Delegates between compressors; feeds unique chunks to research; data compressor targets unique kernels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .video_compressor import video_compress
from .audio_compressor import audio_compress
from .library_compressor import library_compress
from .data_compressor import data_compress, compress_unique_kernels

log = logging.getLogger("unified_semantic_archiver.ring_orchestrator")

COMPRESSORS = ("video", "audio", "library", "data")


def run_ring(
    media_path: Path,
    media_type: str,
    out_dir: Path,
    *,
    db_path: Path | None = None,
    config: dict | None = None,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """
    Run the appropriate compressor for media_type.
    Each compressor can delegate to neighbors (e.g. video uses audio for soundtrack).
    """
    out_dir = Path(out_dir)
    media_path = Path(media_path)
    cb = progress_callback or (lambda _p, _v, _m: None)

    if media_type == "video":
        return video_compress(media_path, out_dir, db_path=db_path, config=config, progress_callback=cb)
    if media_type == "image":
        from .video_compressor import image_compress
        return image_compress(media_path, out_dir, db_path=db_path, config=config, progress_callback=cb)
    if media_type == "audio":
        return audio_compress(media_path, out_dir, db_path=db_path, config=config, progress_callback=cb)
    if media_type == "library":
        return library_compress(media_path, out_dir, db_path=db_path, config=config, progress_callback=cb)
    if media_type == "data":
        return data_compress(media_path, out_dir, db_path=db_path, config=config, progress_callback=cb)

    raise ValueError(f"Unknown media_type: {media_type}. Use one of {COMPRESSORS}")


def run_unique_kernel_pass(
    db_path: Path,
    *,
    limit: int = 10,
    progress_callback: Callable[[str, float, str], None] | None = None,
) -> dict:
    """Data compressor targets unique kernels from other compressors."""
    return compress_unique_kernels(db_path, limit=limit, progress_callback=progress_callback)
