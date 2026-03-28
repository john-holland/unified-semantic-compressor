import json
import types
from pathlib import Path

from unified_semantic_archiver.media.minimization.cairn import build_residual_stream, decode_residual_stream
from unified_semantic_archiver.media.minimization.loaders import load_model_from_config
from unified_semantic_archiver.media.minimization.pipeline import MinimizationPipeline, run_minimization
from unified_semantic_archiver.media.minimization.stages_default import (
    DefaultExtractAdapter,
    DefaultLogisticScoreAdapter,
    DefaultQuadtreeBucketAdapter,
    DefaultSelectionAdapter,
    DefaultThesaurusTokenizeAdapter,
)
from unified_semantic_archiver.media.minimization.types import MinimizationContext


class _NullPersistAdapter:
    def run(self, _ctx, result):
        return result


def test_json_model_scores_probability(tmp_path: Path):
    model_path = tmp_path / "model.json"
    model_path.write_text(
        json.dumps(
            {
                "intercept": -1.0,
                "coefficients": {"token_density": 2.0, "bucket_depth_norm": 0.5},
            }
        ),
        encoding="utf-8",
    )
    model = load_model_from_config(
        {"minimization": {"model": {"path_json": str(model_path), "format_preference": "json_first"}}}
    )
    score = model.score_probability({"token_density": 0.8, "bucket_depth_norm": 0.5})
    assert 0.0 < score < 1.0
    assert score > 0.5


def test_missing_joblib_falls_back_to_default_model():
    model = load_model_from_config(
        {
            "minimization": {
                "model": {
                    "path_joblib": "missing-model.joblib",
                    "format_preference": "joblib_first",
                }
            }
        }
    )
    score = model.score_probability({"token_density": 0.5, "bucket_depth_norm": 0.4})
    assert 0.0 < score < 1.0


def test_quadtree_bucketing_is_deterministic(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight aircraft sky cloud terrain", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={"minimization": {"quadtree": {"max_depth": 3}}},
    )
    extracted = DefaultExtractAdapter().run(ctx)
    tokenized = DefaultThesaurusTokenizeAdapter().run(ctx, extracted)
    buckets_a = DefaultQuadtreeBucketAdapter().run(ctx, extracted, tokenized)
    buckets_b = DefaultQuadtreeBucketAdapter().run(ctx, extracted, tokenized)
    assert [b.bucket_path for b in buckets_a] == [b.bucket_path for b in buckets_b]


def test_style_description_features_are_emitted(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight aircraft sky cloud terrain", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={"minimization": {"quadtree": {"max_depth": 2}}},
        video_style_description="baroque flight cloud terrain",
    )
    extracted = DefaultExtractAdapter().run(ctx)
    tokenized = DefaultThesaurusTokenizeAdapter().run(ctx, extracted)
    buckets = DefaultQuadtreeBucketAdapter().run(ctx, extracted, tokenized)
    assert buckets
    assert "style_description_density" in buckets[0].features
    assert "style_alignment_ratio" in buckets[0].features
    assert buckets[0].features["style_description_density"] > 0.0


def test_style_description_can_raise_score(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight aircraft sky cloud terrain", encoding="utf-8")
    base_ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={},
    )
    styled_ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={},
        video_style_description="flight aircraft sky cloud terrain",
    )
    extract = DefaultExtractAdapter()
    tokenize = DefaultThesaurusTokenizeAdapter()
    bucketize = DefaultQuadtreeBucketAdapter()
    scorer = DefaultLogisticScoreAdapter()
    base_bucket = bucketize.run(base_ctx, extract.run(base_ctx), tokenize.run(base_ctx, extract.run(base_ctx)))[0]
    styled_bucket = bucketize.run(styled_ctx, extract.run(styled_ctx), tokenize.run(styled_ctx, extract.run(styled_ctx)))[0]
    base_score = scorer.run(base_ctx, extract.run(base_ctx), tokenize.run(base_ctx, extract.run(base_ctx)), [base_bucket])[0].score
    styled_score = scorer.run(
        styled_ctx,
        extract.run(styled_ctx),
        tokenize.run(styled_ctx, extract.run(styled_ctx)),
        [styled_bucket],
    )[0].score
    assert styled_score >= base_score


def test_glm_default_matches_logistic_when_neutral(tmp_path: Path):
    model_path = tmp_path / "model.json"
    model_path.write_text(
        json.dumps({"intercept": -1.0, "coefficients": {"token_density": 2.0, "style_alignment_ratio": 0.7}}),
        encoding="utf-8",
    )
    features = {"token_density": 0.8, "style_alignment_ratio": 0.25}
    base_model = load_model_from_config(
        {"minimization": {"model": {"path_json": str(model_path), "format_preference": "json_first"}}}
    )
    glm_model = load_model_from_config(
        {
            "minimization": {
                "model": {
                    "path_json": str(model_path),
                    "format_preference": "json_first",
                    "glm": {
                        "enabled": True,
                        "family": "binomial",
                        "link": "logit",
                        "l1_alpha": 0.0,
                        "l2_alpha": 0.0,
                        "temperature": 1.0,
                    },
                }
            }
        }
    )
    assert abs(base_model.score_probability(features) - glm_model.score_probability(features)) < 1e-9


def test_glm_non_default_tuning_changes_probability(tmp_path: Path):
    model_path = tmp_path / "model.json"
    model_path.write_text(
        json.dumps({"intercept": -0.3, "coefficients": {"token_density": 1.2, "style_alignment_ratio": 0.8}}),
        encoding="utf-8",
    )
    features = {"token_density": 0.9, "style_alignment_ratio": 0.4}
    base_model = load_model_from_config(
        {"minimization": {"model": {"path_json": str(model_path), "format_preference": "json_first"}}}
    )
    tuned_model = load_model_from_config(
        {
            "minimization": {
                "model": {
                    "path_json": str(model_path),
                    "format_preference": "json_first",
                    "glm": {
                        "enabled": True,
                        "family": "poisson",
                        "link": "log",
                        "l1_alpha": 0.05,
                        "l2_alpha": 0.5,
                        "temperature": 0.9,
                    },
                }
            }
        }
    )
    base_score = base_model.score_probability(features)
    tuned_score = tuned_model.score_probability(features)
    assert 0.0 < tuned_score < 1.0
    assert abs(tuned_score - base_score) > 1e-6


def test_glm_with_missing_joblib_still_falls_back(tmp_path: Path):
    model = load_model_from_config(
        {
            "minimization": {
                "model": {
                    "path_joblib": str(tmp_path / "missing-model.joblib"),
                    "format_preference": "joblib_first",
                    "glm": {"enabled": True, "family": "binomial", "link": "logit"},
                }
            }
        }
    )
    score = model.score_probability({"token_density": 0.5, "style_alignment_ratio": 0.4})
    assert 0.0 < score < 1.0


def test_stage_swapping_contract(tmp_path: Path):
    class FixedSelectAdapter:
        def run(self, _ctx, scored):
            refs = [f"swapped:{row.frame_index}" for row in scored[:3]]
            return types.SimpleNamespace(unique_chunk_refs=refs, bucket_scores=scored[:3], diagnostics={})

    script = tmp_path / "script.txt"
    script.write_text("token one two three four", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={"minimization": {"enabled": True}},
    )
    pipeline = MinimizationPipeline(
        extract=DefaultExtractAdapter(),
        tokenize=DefaultThesaurusTokenizeAdapter(),
        bucket=DefaultQuadtreeBucketAdapter(),
        score=DefaultLogisticScoreAdapter(),
        select=FixedSelectAdapter(),
        persist=_NullPersistAdapter(),
    )
    result = pipeline.run(ctx)
    assert len(result.unique_chunk_refs) == 3
    assert result.unique_chunk_refs[0].startswith("swapped:")


def test_run_minimization_disabled_returns_empty(tmp_path: Path):
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=None,
        out_dir=tmp_path,
        grid_size=2,
        config={"minimization": {"enabled": False}},
    )
    result = run_minimization(ctx)
    assert result.unique_chunk_refs == []
    assert result.diagnostics["enabled"] is False


def test_cairn_residual_codec_roundtrip():
    orig = [
        {"plane_id": 1, "stone_path": "01", "pitch_norm": 0.2, "energy_norm": 0.3, "flux_norm": 0.1},
        {"plane_id": 1, "stone_path": "02", "pitch_norm": 0.22, "energy_norm": 0.33, "flux_norm": 0.11},
        {"plane_id": 2, "stone_path": "03", "pitch_norm": 0.18, "energy_norm": 0.29, "flux_norm": 0.09},
    ]
    gen = [
        {"plane_id": 0, "stone_path": "0", "pitch_norm": 0.1, "energy_norm": 0.2, "flux_norm": 0.05},
        {"plane_id": 1, "stone_path": "0", "pitch_norm": 0.19, "energy_norm": 0.31, "flux_norm": 0.10},
        {"plane_id": 1, "stone_path": "0", "pitch_norm": 0.17, "energy_norm": 0.25, "flux_norm": 0.08},
    ]
    packed = build_residual_stream(orig, gen)
    decoded = decode_residual_stream(packed["payload"])
    assert len(decoded) == 3
    assert decoded[0][0] == 1  # plane delta
    assert isinstance(packed["sha256"], str)


def test_cohort_routing_selects_adapter_set(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight plane sky cloud mountain", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        tenant_id="tenant-a",
        job_id="job-a",
        config={
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "default"},
                "experiments": {
                    "enabled": True,
                    "cohort_key": "job",
                    "cohorts": {"planar_hyperplane_v1": 100},
                },
            }
        },
    )
    result = run_minimization(ctx)
    assert result.diagnostics.get("adapter_set") == "planar_hyperplane_v1"


def test_cohort_portfolio_percent_min_floor(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight plane sky cloud mountain", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        tenant_id="tenant-b",
        job_id="job-b",
        config={
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "default"},
                "experiments": {
                    "enabled": True,
                    "cohort_key": "job",
                    "portfolio_percent_min": 100,
                    "cohorts": {"planar_hyperplane_v1": 1},
                },
            }
        },
    )
    result = run_minimization(ctx)
    assert result.diagnostics.get("adapter_set") == "planar_hyperplane_v1"


def test_cairn_adapter_set_graceful_without_audio(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("flight plane sky cloud mountain", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "cairn_audio_v1"},
                "cairn": {"enabled": True},
            }
        },
    )
    result = run_minimization(ctx)
    assert result.diagnostics.get("enabled") is True
    assert isinstance(result.unique_chunk_refs, list)


def test_adapter_requirement_fallback(tmp_path: Path):
    script = tmp_path / "script.txt"
    script.write_text("token one two three", encoding="utf-8")
    ctx = MinimizationContext(
        video_path=tmp_path / "input.mp4",
        resultant_path=None,
        diff_path=None,
        script_path=script,
        out_dir=tmp_path,
        grid_size=2,
        config={
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "audio_captioning_v1"},
                "adapter_requirements": {
                    "audio_captioning_v1": {
                        "required_python_packages": ["__definitely_missing_pkg__"],
                        "runtime_fallback_adapter": "default",
                    }
                },
            }
        },
    )
    result = run_minimization(ctx)
    req = result.diagnostics.get("adapter_requirements", {})
    assert req.get("is_ready") is False
    assert "__definitely_missing_pkg__" in (req.get("missing", {}).get("packages") or [])
    assert result.diagnostics.get("adapter_set") == "default"
