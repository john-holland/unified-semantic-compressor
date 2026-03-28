from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .cairn import write_cairn_sidecars
from .loaders import load_model_from_config
from .types import Bucket, ExtractedData, MinimizationContext, MinimizationResult, ScoredBucket, TokenizedData


class DefaultExtractAdapter:
    def run(self, ctx: MinimizationContext) -> ExtractedData:
        script_text = ""
        if ctx.script_path and Path(ctx.script_path).is_file():
            script_text = Path(ctx.script_path).read_text(encoding="utf-8", errors="ignore")
        style_description = str(
            ctx.video_style_description
            or ctx.config.get("script", {}).get("video_style_description", "")
            or ""
        ).strip()
        frame_count = max(8, min(240, max(1, len(script_text.split()))))
        frames = [
            {"frame_index": float(i), "timestamp_sec": float(i), "motion_hint": (i % 10) / 10.0}
            for i in range(frame_count)
        ]
        diff_size = float(Path(ctx.diff_path).stat().st_size) if ctx.diff_path and Path(ctx.diff_path).is_file() else 0.0
        return ExtractedData(
            script_text=script_text,
            frames=frames,
            metadata={
                "frame_count": frame_count,
                "diff_size_bytes": diff_size,
                "video_style_description": style_description,
            },
        )


def _discover_audio_path(out_dir: Path) -> Path | None:
    for name in ("audio.flac", "audio.aac", "audio.mp3", "audio.wav"):
        p = out_dir / name
        if p.is_file():
            return p
    return None


def _load_cairn_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


class CairnExtractAdapter(DefaultExtractAdapter):
    def run(self, ctx: MinimizationContext) -> ExtractedData:
        extracted = super().run(ctx)
        mini = ctx.config.get("minimization", {})
        cairn_cfg = mini.get("cairn", {})
        enabled = bool(cairn_cfg.get("enabled", True))
        if not enabled:
            extracted.metadata["cairn_enabled"] = False
            return extracted

        out_dir = Path(ctx.out_dir)
        original_audio = _discover_audio_path(out_dir)
        if original_audio is None:
            extracted.metadata["cairn_enabled"] = False
            extracted.metadata["cairn_error"] = "audio track not found in out_dir"
            return extracted

        generated_audio_candidate = out_dir / "resultant_audio.wav"
        emit_resultant_audio = bool(cairn_cfg.get("emit_resultant_audio", False))
        if ctx.resultant_path and Path(ctx.resultant_path).is_file():
            try:
                import subprocess
                if emit_resultant_audio:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-v",
                            "error",
                            "-i",
                            str(ctx.resultant_path),
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            str(generated_audio_candidate),
                        ],
                        capture_output=True,
                        check=True,
                        timeout=120,
                    )
                else:
                    generated_audio_candidate = None
            except Exception:
                generated_audio_candidate = None
        else:
            generated_audio_candidate = None

        try:
            sidecars = write_cairn_sidecars(
                original_audio_path=original_audio,
                generated_audio_path=generated_audio_candidate if generated_audio_candidate and generated_audio_candidate.is_file() else None,
                out_dir=out_dir,
                max_depth=int(cairn_cfg.get("max_depth", 3)),
                write_debug_json=bool(cairn_cfg.get("write_debug_json", False)),
            )
            cairn_payload = _load_cairn_json(Path(sidecars["json_path"])) if sidecars.get("json_path") else None
            stones = []
            if cairn_payload:
                stones = cairn_payload.get("stones", [])
            extracted.metadata.update(
                {
                    "cairn_enabled": True,
                    "cairn": sidecars,
                    "cairn_stones": stones,
                }
            )
        except Exception as exc:
            extracted.metadata["cairn_enabled"] = False
            extracted.metadata["cairn_error"] = str(exc)
        return extracted


class DefaultThesaurusTokenizeAdapter:
    _synonyms = {
        "flight": "aircraft",
        "plane": "aircraft",
        "jet": "aircraft",
        "car": "vehicle",
        "truck": "vehicle",
        "road": "terrain",
        "mountain": "terrain",
        "sky": "atmosphere",
        "cloud": "atmosphere",
    }

    def run(self, ctx: MinimizationContext, extracted: ExtractedData) -> TokenizedData:
        words = re.findall(r"[A-Za-z0-9_]+", extracted.script_text.lower())
        normalized = [self._synonyms.get(w, w) for w in words]
        style_text = str(extracted.metadata.get("video_style_description", "")).lower()
        style_words = re.findall(r"[A-Za-z0-9_]+", style_text)
        style_set = set(style_words)
        counts = Counter(normalized)
        total = max(1, sum(counts.values()))
        probs = [c / total for c in counts.values()]
        entropy = -sum(p * math.log2(max(1e-12, p)) for p in probs)
        # Keep strongest tokens only; enough for compact adapter output.
        top = dict(counts.most_common(32))
        weights = {k: float(v / total) for k, v in top.items()}
        speech_density = float(total) / max(1.0, float(extracted.metadata.get("frame_count", 1)))
        speech_confidence = 0.0 if "whisper failed" in extracted.script_text.lower() else 1.0
        overlap_count = sum(1 for word in normalized if word in style_set)
        style_alignment_ratio = float(overlap_count) / max(1, len(normalized))
        style_description_density = float(len(style_words)) / max(1.0, float(extracted.metadata.get("frame_count", 1)))
        return TokenizedData(
            tokens=weights,
            token_entropy=float(entropy),
            metadata={
                "token_count": total,
                "speech_density": speech_density,
                "speech_confidence": speech_confidence,
                "style_token_count": len(style_words),
                "style_alignment_ratio": style_alignment_ratio,
                "style_description_density": style_description_density,
            },
        )


class CairnAlignedTokenizeAdapter(DefaultThesaurusTokenizeAdapter):
    def run(self, ctx: MinimizationContext, extracted: ExtractedData) -> TokenizedData:
        tok = super().run(ctx, extracted)
        words = re.findall(r"[A-Za-z0-9_]+", extracted.script_text.lower())
        stones = extracted.metadata.get("cairn_stones", []) or []
        # Lightweight temporal alignment: map token spans proportionally onto stone indices.
        aligned: list[dict[str, Any]] = []
        if words and stones:
            count = len(words)
            span = max(1, len(stones) // count)
            for i, w in enumerate(words[:128]):
                s0 = i * span
                s1 = min(len(stones), s0 + span)
                aligned.append({"token": w, "stone_start": s0, "stone_end": s1})
        tok.metadata["whisper_cairn_alignment"] = aligned
        sfx_markers = re.findall(r"\[audio effects\]|\bsfx\b|\bimpact\b|\bengine\b|\bwind\b", extracted.script_text.lower())
        tok.metadata["sfx_caption_density"] = float(len(sfx_markers)) / max(1, len(words))
        unique_words = len(set(words))
        tok.metadata["sfx_caption_novelty"] = float(unique_words) / max(1, len(words))
        return tok


class DefaultQuadtreeBucketAdapter:
    def run(self, ctx: MinimizationContext, extracted: ExtractedData, tokens: TokenizedData) -> list[Bucket]:
        mini = ctx.config.get("minimization", {})
        quad = mini.get("quadtree", {})
        depth = int(quad.get("max_depth", 2))
        depth = max(1, min(5, depth))
        frame_total = max(1, len(extracted.frames))
        buckets: list[Bucket] = []
        for frame_idx, frame in enumerate(extracted.frames):
            temporal_pos = frame_idx / frame_total
            # Deterministic pseudo quadtree path per frame.
            path_digits = [(frame_idx + i * 3) % 4 for i in range(depth)]
            path = "".join(str(d) for d in path_digits)
            buckets.append(
                Bucket(
                    frame_index=frame_idx,
                    timestamp_sec=float(frame["timestamp_sec"]),
                    bucket_path=path,
                    depth=depth,
                    features={
                        "token_density": float(sum(tokens.tokens.values())),
                        "token_entropy": float(tokens.token_entropy),
                        "speech_density": float(tokens.metadata.get("speech_density", 0.0)),
                        "speech_confidence": float(tokens.metadata.get("speech_confidence", 0.0)),
                        "style_description_density": float(tokens.metadata.get("style_description_density", 0.0)),
                        "style_alignment_ratio": float(tokens.metadata.get("style_alignment_ratio", 0.0)),
                        "bucket_depth_norm": depth / 5.0,
                        "temporal_position": temporal_pos,
                        "diff_size_norm": float(extracted.metadata.get("diff_size_bytes", 0.0)) / (10.0 * 1024 * 1024),
                    },
                )
            )
        return buckets


class CairnFeatureBucketAdapter(DefaultQuadtreeBucketAdapter):
    def run(self, ctx: MinimizationContext, extracted: ExtractedData, tokens: TokenizedData) -> list[Bucket]:
        buckets = super().run(ctx, extracted, tokens)
        stones = extracted.metadata.get("cairn_stones", []) or []
        if not stones:
            return buckets
        transitions = 0
        for i in range(1, len(stones)):
            if stones[i].get("stone_path") != stones[i - 1].get("stone_path"):
                transitions += 1
        trans_rate = transitions / max(1, len(stones) - 1)
        plane_transitions = 0
        for i in range(1, len(stones)):
            if stones[i].get("plane_id") != stones[i - 1].get("plane_id"):
                plane_transitions += 1
        plane_rate = plane_transitions / max(1, len(stones) - 1)
        dominant = Counter(str(s.get("stone_path", "")) for s in stones).most_common(1)
        dominant_count = dominant[0][1] if dominant else 0
        dominant_persistence = dominant_count / max(1, len(stones))
        stone_entropy = 0.0
        counts = Counter(str(s.get("stone_path", "")) for s in stones)
        total = max(1, sum(counts.values()))
        for c in counts.values():
            p = c / total
            stone_entropy -= p * math.log2(max(1e-12, p))

        for b in buckets:
            s = stones[b.frame_index % len(stones)]
            b.features["plane_id"] = float(s.get("plane_id", 0))
            b.features["plane_transition_rate"] = float(plane_rate)
            b.features["stone_entropy"] = float(stone_entropy)
            b.features["stone_transition_rate"] = float(trans_rate)
            b.features["pitch_delta_norm"] = float(s.get("pitch_norm", 0.0))
            b.features["energy_slope"] = float(s.get("energy_norm", 0.0) - s.get("flux_norm", 0.0))
            b.features["dominant_stone_persistence"] = float(dominant_persistence)
            b.features["sfx_caption_density"] = float(tokens.metadata.get("sfx_caption_density", 0.0))
            b.features["sfx_caption_novelty"] = float(tokens.metadata.get("sfx_caption_novelty", 0.0))
        return buckets


class CairnResidualBucketAdapter(CairnFeatureBucketAdapter):
    def run(self, ctx: MinimizationContext, extracted: ExtractedData, tokens: TokenizedData) -> list[Bucket]:
        buckets = super().run(ctx, extracted, tokens)
        cairn_meta = extracted.metadata.get("cairn", {}) or {}
        residual_path = cairn_meta.get("residual_bin_path")
        residual_size = 0.0
        if residual_path:
            p = Path(str(residual_path))
            if p.is_file():
                residual_size = float(p.stat().st_size)
        stone_count = float(cairn_meta.get("stone_count", 0) or 0.0)
        residual_per_stone = (residual_size / stone_count) if stone_count > 0 else 0.0
        for b in buckets:
            b.features["cairn_residual_size_norm"] = residual_size / (1024.0 * 1024.0)
            b.features["cairn_residual_per_stone"] = residual_per_stone / 1024.0
        return buckets


class DefaultLogisticScoreAdapter:
    def run(
        self,
        ctx: MinimizationContext,
        extracted: ExtractedData,
        tokens: TokenizedData,
        buckets: list[Bucket],
    ) -> list[ScoredBucket]:
        model = load_model_from_config(ctx.config)
        out: list[ScoredBucket] = []
        for bucket in buckets:
            score = float(model.score_probability(bucket.features))
            out.append(
                ScoredBucket(
                    frame_index=bucket.frame_index,
                    timestamp_sec=bucket.timestamp_sec,
                    bucket_path=bucket.bucket_path,
                    depth=bucket.depth,
                    score=score,
                    features=dict(bucket.features),
                )
            )
        return out


class HyperplaneScoreAdapter(DefaultLogisticScoreAdapter):
    def run(
        self,
        ctx: MinimizationContext,
        extracted: ExtractedData,
        tokens: TokenizedData,
        buckets: list[Bucket],
    ) -> list[ScoredBucket]:
        mini = ctx.config.get("minimization", {})
        hp = mini.get("hyperplane", {})
        intercept = float(hp.get("intercept", -1.8))
        coefs = hp.get("coefficients") or {
            "token_density": 0.8,
            "token_entropy": 0.5,
            "bucket_depth_norm": 0.7,
            "temporal_position": 0.2,
            "diff_size_norm": 0.5,
            "stone_entropy": 0.6,
            "stone_transition_rate": 0.6,
            "pitch_delta_norm": 0.7,
            "plane_transition_rate": 0.4,
        }
        piecewise = hp.get("piecewise_by_plane", {}) or {}

        out: list[ScoredBucket] = []
        for bucket in buckets:
            plane = int(bucket.features.get("plane_id", 0))
            local = piecewise.get(str(plane), {})
            local_intercept = float(local.get("intercept", intercept))
            local_coefs = local.get("coefficients", coefs)
            z = local_intercept
            for k, v in bucket.features.items():
                z += float(local_coefs.get(k, 0.0)) * float(v)
            score = 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, z))))
            out.append(
                ScoredBucket(
                    frame_index=bucket.frame_index,
                    timestamp_sec=bucket.timestamp_sec,
                    bucket_path=bucket.bucket_path,
                    depth=bucket.depth,
                    score=float(score),
                    features=dict(bucket.features),
                )
            )
        return out


class DefaultSelectionAdapter:
    def run(self, ctx: MinimizationContext, scored: list[ScoredBucket]) -> MinimizationResult:
        mini = ctx.config.get("minimization", {})
        threshold = float(mini.get("threshold", 0.55))
        max_refs = int(mini.get("max_refs", 128))
        chosen = [s for s in scored if s.score >= threshold]
        if not chosen:
            chosen = sorted(scored, key=lambda s: s.score, reverse=True)[: min(12, len(scored))]
        else:
            chosen = sorted(chosen, key=lambda s: s.score, reverse=True)[:max_refs]
        refs = [f"f{row.frame_index}:q{row.bucket_path}:{row.score:.3f}" for row in chosen]
        return MinimizationResult(
            unique_chunk_refs=refs,
            bucket_scores=chosen,
            diagnostics={
                "threshold": threshold,
                "selected_count": len(chosen),
                "scored_count": len(scored),
            },
        )


class DefaultPersistAdapter:
    def run(self, ctx: MinimizationContext, result: MinimizationResult) -> MinimizationResult:
        payload: dict[str, Any] = {
            "source": ctx.source,
            "tenant_id": ctx.tenant_id,
            "job_id": ctx.job_id,
            "unique_chunk_refs": result.unique_chunk_refs,
            "diagnostics": result.diagnostics,
            "bucket_scores": [
                {
                    "frame_index": s.frame_index,
                    "timestamp_sec": s.timestamp_sec,
                    "bucket_path": s.bucket_path,
                    "depth": s.depth,
                    "score": s.score,
                }
                for s in result.bucket_scores
            ],
        }
        out_file = Path(ctx.out_dir) / "minimization_report.json"
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result.diagnostics["report_path"] = str(out_file)
        return result
