from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .adapter_requirements import evaluate_adapter_requirements
from .protocols import BucketAdapter, ExtractAdapter, PersistAdapter, ScoreAdapter, SelectAdapter, TokenizeAdapter
from .stages_default import (
    CairnAlignedTokenizeAdapter,
    CairnExtractAdapter,
    CairnFeatureBucketAdapter,
    CairnResidualBucketAdapter,
    DefaultExtractAdapter,
    DefaultLogisticScoreAdapter,
    DefaultPersistAdapter,
    DefaultQuadtreeBucketAdapter,
    DefaultSelectionAdapter,
    DefaultThesaurusTokenizeAdapter,
    HyperplaneScoreAdapter,
)
from .types import MinimizationContext, MinimizationResult


@dataclass
class MinimizationPipeline:
    extract: ExtractAdapter
    tokenize: TokenizeAdapter
    bucket: BucketAdapter
    score: ScoreAdapter
    select: SelectAdapter
    persist: PersistAdapter

    def run(self, ctx: MinimizationContext) -> MinimizationResult:
        extracted = self.extract.run(ctx)
        tokenized = self.tokenize.run(ctx, extracted)
        buckets = self.bucket.run(ctx, extracted, tokenized)
        scored = self.score.run(ctx, extracted, tokenized, buckets)
        result = self.select.run(ctx, scored)
        return self.persist.run(ctx, result)


def _resolve_stage_map(adapter_set: str):
    if adapter_set == "cairn_audio_v1":
        return {
            "extract": CairnExtractAdapter,
            "tokenize": CairnAlignedTokenizeAdapter,
            "bucket": CairnFeatureBucketAdapter,
            "score": DefaultLogisticScoreAdapter,
            "select": DefaultSelectionAdapter,
            "persist": DefaultPersistAdapter,
        }
    if adapter_set == "cairn_residual_v1":
        return {
            "extract": CairnExtractAdapter,
            "tokenize": CairnAlignedTokenizeAdapter,
            "bucket": CairnResidualBucketAdapter,
            "score": DefaultLogisticScoreAdapter,
            "select": DefaultSelectionAdapter,
            "persist": DefaultPersistAdapter,
        }
    if adapter_set == "planar_hyperplane_v1":
        return {
            "extract": CairnExtractAdapter,
            "tokenize": CairnAlignedTokenizeAdapter,
            "bucket": CairnFeatureBucketAdapter,
            "score": HyperplaneScoreAdapter,
            "select": DefaultSelectionAdapter,
            "persist": DefaultPersistAdapter,
        }
    if adapter_set == "audio_captioning_v1":
        return {
            "extract": CairnExtractAdapter,
            "tokenize": CairnAlignedTokenizeAdapter,
            "bucket": CairnFeatureBucketAdapter,
            "score": DefaultLogisticScoreAdapter,
            "select": DefaultSelectionAdapter,
            "persist": DefaultPersistAdapter,
        }
    if adapter_set == "glm_tuned_v1":
        return {
            "extract": DefaultExtractAdapter,
            "tokenize": DefaultThesaurusTokenizeAdapter,
            "bucket": DefaultQuadtreeBucketAdapter,
            "score": DefaultLogisticScoreAdapter,
            "select": DefaultSelectionAdapter,
            "persist": DefaultPersistAdapter,
        }
    return {
        "extract": DefaultExtractAdapter,
        "tokenize": DefaultThesaurusTokenizeAdapter,
        "bucket": DefaultQuadtreeBucketAdapter,
        "score": DefaultLogisticScoreAdapter,
        "select": DefaultSelectionAdapter,
        "persist": DefaultPersistAdapter,
    }


def _resolve_cohort_adapter_set(config: dict, context: MinimizationContext, default_adapter_set: str) -> str:
    mini = config.get("minimization", {})
    exp = mini.get("experiments", {})
    if not bool(exp.get("enabled", False)):
        return default_adapter_set
    key_mode = str(exp.get("cohort_key", "hash"))
    if key_mode == "tenant":
        seed = context.tenant_id or "default"
    elif key_mode == "job":
        seed = context.job_id or "job-unknown"
    else:
        seed = "|".join(
            [
                context.tenant_id or "",
                context.job_id or "",
                str(context.video_path),
                str(context.out_dir),
            ]
        )
    hv = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    cohorts = exp.get("cohorts") or {}
    min_pct = max(0, min(100, int(exp.get("portfolio_percent_min", 0))))
    # Supports dict {"adapter_set": pct} or {"name":{"adapter_set":"x","percent":y}}.
    weighted: list[tuple[str, int]] = []
    for name, raw in cohorts.items():
        if isinstance(raw, dict):
            adapter_set = str(raw.get("adapter_set", name))
            pct = int(raw.get("percent", 0))
        else:
            adapter_set = str(name)
            pct = int(raw)
        if pct <= 0:
            continue
        weighted.append((adapter_set, max(min_pct, pct)))
    if not weighted:
        return default_adapter_set
    # Normalize to 100 so routing threshold is deterministic and bounded.
    total = sum(p for _, p in weighted)
    if total <= 0:
        return default_adapter_set
    scaled = [p * 100.0 / total for _, p in weighted]
    bases = [int(x) for x in scaled]
    shortfall = 100 - sum(bases)
    order = sorted(range(len(weighted)), key=lambda i: scaled[i] - bases[i], reverse=True)
    for i in range(max(0, shortfall)):
        bases[order[i % len(order)]] += 1
    normalized = [(weighted[i][0], bases[i]) for i in range(len(weighted))]
    cursor = 0
    for adapter_set, pct in normalized:
        cursor += pct
        if hv < cursor:
            return adapter_set
    return default_adapter_set


def build_pipeline(config: dict) -> MinimizationPipeline:
    return _build_pipeline_for_context(config, None)


def _build_pipeline_for_context(config: dict, context: MinimizationContext | None) -> MinimizationPipeline:
    mini = config.get("minimization", {})
    pipeline_cfg = mini.get("pipeline", {})
    adapter_set = str(pipeline_cfg.get("adapter_set", "minimization-usc-adapter"))
    if context is not None:
        adapter_set = _resolve_cohort_adapter_set(config, context, adapter_set)
        req_status = evaluate_adapter_requirements(config, adapter_set)
        if not req_status["is_ready"]:
            fallback = req_status["runtime_fallback_adapter"]
            adapter_set = fallback
    else:
        req_status = evaluate_adapter_requirements(config, adapter_set)
        if not req_status["is_ready"]:
            adapter_set = req_status["runtime_fallback_adapter"]
    stage_map = _resolve_stage_map(adapter_set)
    stage_names = pipeline_cfg.get("stages", {})

    def make(name: str):
        stage_id = str(stage_names.get(name, "default"))
        _ = stage_id  # placeholder for future stage registry keyed by stage ID
        return stage_map[name]()

    pipeline = MinimizationPipeline(
        extract=make("extract"),
        tokenize=make("tokenize"),
        bucket=make("bucket"),
        score=make("score"),
        select=make("select"),
        persist=make("persist"),
    )
    setattr(pipeline, "_selected_adapter_set", adapter_set)
    setattr(pipeline, "_adapter_requirement_status", req_status)
    return pipeline


def run_minimization(context: MinimizationContext) -> MinimizationResult:
    enabled = bool(context.config.get("minimization", {}).get("enabled", False))
    if not enabled:
        return MinimizationResult(unique_chunk_refs=[], bucket_scores=[], diagnostics={"enabled": False})
    pipeline = _build_pipeline_for_context(context.config, context)
    result = pipeline.run(context)
    result.diagnostics["enabled"] = True
    result.diagnostics["adapter_set"] = getattr(pipeline, "_selected_adapter_set", "minimization-usc-adapter")
    result.diagnostics["adapter_requirements"] = getattr(pipeline, "_adapter_requirement_status", {})
    report_path = result.diagnostics.get("report_path")
    if report_path:
        try:
            import json
            from pathlib import Path

            path = Path(str(report_path))
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    payload["diagnostics"] = result.diagnostics
                    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
    return result
