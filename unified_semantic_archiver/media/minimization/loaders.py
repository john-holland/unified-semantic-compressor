from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    GlmTuningConfig,
    LogisticModel,
    SklearnModelAdapter,
    TunedGlmModel,
    TunedProbabilityAdapter,
    default_self_evident_model,
)


def load_json_model(path: Path) -> LogisticModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "intercept" not in payload:
        raise ValueError("JSON model is missing intercept")
    if "coefficients" in payload and isinstance(payload["coefficients"], dict):
        coeffs = {str(k): float(v) for k, v in payload["coefficients"].items()}
    elif "feature_order" in payload and "weights" in payload:
        order = [str(v) for v in payload["feature_order"]]
        vals = [float(v) for v in payload["weights"]]
        coeffs = dict(zip(order, vals, strict=False))
    else:
        raise ValueError("JSON model needs coefficients or feature_order+weights")
    return LogisticModel(intercept=float(payload["intercept"]), coefficients=coeffs)


def load_joblib_model(path: Path, feature_order: list[str] | None = None) -> SklearnModelAdapter:
    try:
        import joblib
    except ImportError as exc:
        raise RuntimeError("joblib is not installed") from exc
    model = joblib.load(path)
    if feature_order is None:
        feature_order = [
            "token_density",
            "token_entropy",
            "speech_density",
            "speech_confidence",
            "style_description_density",
            "style_alignment_ratio",
            "bucket_depth_norm",
            "temporal_position",
            "diff_size_norm",
            "plane_id",
            "plane_transition_rate",
            "stone_entropy",
            "stone_transition_rate",
            "pitch_delta_norm",
            "energy_slope",
            "dominant_stone_persistence",
            "sfx_caption_density",
            "sfx_caption_novelty",
        ]
    return SklearnModelAdapter(model=model, feature_order=feature_order)


def _parse_glm_config(value: Any) -> GlmTuningConfig:
    raw = value if isinstance(value, dict) else {}
    return GlmTuningConfig(
        enabled=bool(raw.get("enabled", False)),
        family=str(raw.get("family", "binomial")),
        link=str(raw.get("link", "logit")),
        l1_alpha=float(raw.get("l1_alpha", 0.0)),
        l2_alpha=float(raw.get("l2_alpha", 0.0)),
        temperature=float(raw.get("temperature", 1.0)),
    )


def _apply_glm_tuning(model: object, glm_cfg: GlmTuningConfig):
    if not glm_cfg.enabled:
        return model
    if isinstance(model, LogisticModel):
        return TunedGlmModel(
            intercept=model.intercept,
            coefficients=dict(model.coefficients),
            glm=glm_cfg,
        )
    return TunedProbabilityAdapter(base_model=model, glm=glm_cfg)


def load_model_from_config(config: dict[str, Any]):
    mini = config.get("minimization", {})
    model_cfg = mini.get("model", {})
    preference = str(model_cfg.get("format_preference", "json_first")).lower()
    json_path = model_cfg.get("path_json")
    joblib_path = model_cfg.get("path_joblib")
    feature_order = model_cfg.get("feature_order")
    glm_cfg = _parse_glm_config(model_cfg.get("glm"))

    def maybe_load_json():
        if not json_path:
            return None
        path = Path(str(json_path))
        if not path.is_file():
            return None
        return load_json_model(path)

    def maybe_load_joblib():
        if not joblib_path:
            return None
        path = Path(str(joblib_path))
        if not path.is_file():
            return None
        return load_joblib_model(path, feature_order=feature_order)

    loaders = [maybe_load_json, maybe_load_joblib] if preference == "json_first" else [maybe_load_joblib, maybe_load_json]
    for loader in loaders:
        model = loader()
        if model is not None:
            return _apply_glm_tuning(model, glm_cfg)
    return _apply_glm_tuning(default_self_evident_model(), glm_cfg)
