from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MinimizationContext:
    video_path: Path
    resultant_path: Path | None
    diff_path: Path | None
    script_path: Path | None
    out_dir: Path
    grid_size: int
    config: dict[str, Any] = field(default_factory=dict)
    source: str = "compressor"
    tenant_id: str | None = None
    job_id: str | None = None
    video_style_description: str = ""


@dataclass
class ExtractedData:
    script_text: str
    frames: list[dict[str, float]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenizedData:
    tokens: dict[str, float]
    token_entropy: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bucket:
    frame_index: int
    timestamp_sec: float
    bucket_path: str
    depth: int
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class ScoredBucket:
    frame_index: int
    timestamp_sec: float
    bucket_path: str
    depth: int
    score: float
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class MinimizationResult:
    unique_chunk_refs: list[str]
    bucket_scores: list[ScoredBucket]
    diagnostics: dict[str, Any] = field(default_factory=dict)
