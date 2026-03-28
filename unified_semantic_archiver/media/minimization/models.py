from __future__ import annotations

import math
from dataclasses import dataclass, field


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-_clip(value, -50.0, 50.0)))


def _logit(probability: float) -> float:
    p = _clip(probability, 1e-9, 1.0 - 1e-9)
    return math.log(p / (1.0 - p))


def _soft_threshold(value: float, alpha: float) -> float:
    if alpha <= 0.0:
        return value
    if value > alpha:
        return value - alpha
    if value < -alpha:
        return value + alpha
    return 0.0


@dataclass
class LogisticModel:
    intercept: float
    coefficients: dict[str, float] = field(default_factory=dict)

    def score_probability(self, features: dict[str, float]) -> float:
        z = self.intercept
        for name, value in features.items():
            z += self.coefficients.get(name, 0.0) * value
        return _sigmoid(z)


@dataclass
class GlmTuningConfig:
    enabled: bool = False
    family: str = "binomial"
    link: str = "logit"
    l1_alpha: float = 0.0
    l2_alpha: float = 0.0
    temperature: float = 1.0


def _inverse_link(z_value: float, link: str) -> float:
    name = (link or "logit").strip().lower()
    z = _clip(z_value, -50.0, 50.0)
    if name == "identity":
        return z
    if name == "log":
        return math.exp(_clip(z, -20.0, 20.0))
    if name == "probit":
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    if name == "cloglog":
        return 1.0 - math.exp(-math.exp(_clip(z, -20.0, 20.0)))
    return _sigmoid(z)


def _family_probability(mu: float, family: str) -> float:
    name = (family or "binomial").strip().lower()
    if name in {"gaussian", "normal"}:
        return _sigmoid(mu)
    if name == "poisson":
        return 1.0 - math.exp(-max(0.0, mu))
    return _clip(mu, 0.0, 1.0)


@dataclass
class TunedGlmModel:
    intercept: float
    coefficients: dict[str, float] = field(default_factory=dict)
    glm: GlmTuningConfig = field(default_factory=GlmTuningConfig)

    def score_probability(self, features: dict[str, float]) -> float:
        l2_scale = 1.0 / (1.0 + max(0.0, float(self.glm.l2_alpha)))
        z = self.intercept
        for name, value in features.items():
            coef = float(self.coefficients.get(name, 0.0))
            coef = _soft_threshold(coef, max(0.0, float(self.glm.l1_alpha)))
            z += (coef * l2_scale) * value
        temperature = max(1e-6, float(self.glm.temperature))
        z = z / temperature
        mu = _inverse_link(z, self.glm.link)
        return _family_probability(mu, self.glm.family)


@dataclass
class SklearnModelAdapter:
    """Adapter that normalizes sklearn predict_proba to LogisticModel-like API."""

    model: object
    feature_order: list[str]

    def score_probability(self, features: dict[str, float]) -> float:
        row = [[features.get(name, 0.0) for name in self.feature_order]]
        proba = getattr(self.model, "predict_proba")(row)
        if not proba:
            return 0.0
        if len(proba[0]) >= 2:
            return float(proba[0][1])
        return float(proba[0][0])


@dataclass
class TunedProbabilityAdapter:
    base_model: object
    glm: GlmTuningConfig = field(default_factory=GlmTuningConfig)

    def score_probability(self, features: dict[str, float]) -> float:
        base_probability = float(getattr(self.base_model, "score_probability")(features))
        z = _logit(base_probability) / max(1e-6, float(self.glm.temperature))
        mu = _inverse_link(z, self.glm.link)
        return _family_probability(mu, self.glm.family)


def default_self_evident_model() -> LogisticModel:
    # Conservative defaults that bias toward buckets with stronger token density,
    # deeper detail, and higher temporal confidence.
    return LogisticModel(
        intercept=-2.0,
        coefficients={
            "token_density": 1.2,
            "token_entropy": 0.8,
            "speech_density": 0.4,
            "speech_confidence": 0.6,
            "style_description_density": 0.55,
            "style_alignment_ratio": 0.8,
            "bucket_depth_norm": 0.9,
            "temporal_position": 0.3,
            "diff_size_norm": 1.0,
            "plane_id": 0.05,
            "plane_transition_rate": 0.4,
            "stone_entropy": 0.7,
            "stone_transition_rate": 0.6,
            "pitch_delta_norm": 0.75,
            "energy_slope": 0.45,
            "dominant_stone_persistence": 0.5,
            "sfx_caption_density": 0.5,
            "sfx_caption_novelty": 0.35,
        },
    )
