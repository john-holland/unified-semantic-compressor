from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any


DEFAULT_ADAPTER_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "default": {
        "adapter_id": "default",
        "required_python_packages": [],
        "required_binaries": [],
        "required_model_artifacts": [],
        "runtime_fallback_adapter": "default",
    },
    "cairn_audio_v1": {
        "adapter_id": "cairn_audio_v1",
        "required_python_packages": [],
        "required_binaries": ["ffmpeg"],
        "required_model_artifacts": [],
        "runtime_fallback_adapter": "default",
    },
    "cairn_residual_v1": {
        "adapter_id": "cairn_residual_v1",
        "required_python_packages": [],
        "required_binaries": ["ffmpeg"],
        "required_model_artifacts": [],
        "runtime_fallback_adapter": "cairn_audio_v1",
    },
    "planar_hyperplane_v1": {
        "adapter_id": "planar_hyperplane_v1",
        "required_python_packages": [],
        "required_binaries": ["ffmpeg"],
        "required_model_artifacts": [],
        "runtime_fallback_adapter": "default",
    },
    "audio_captioning_v1": {
        "adapter_id": "audio_captioning_v1",
        "required_python_packages": ["transformers", "torch"],
        "required_binaries": ["ffmpeg"],
        "required_model_artifacts": [],
        "runtime_fallback_adapter": "default",
    },
}


def _merge_requirement(config: dict[str, Any], adapter_set: str) -> dict[str, Any]:
    cfg = config.get("minimization", {}).get("adapter_requirements", {}).get(adapter_set, {})
    base = dict(DEFAULT_ADAPTER_REQUIREMENTS.get(adapter_set, DEFAULT_ADAPTER_REQUIREMENTS["default"]))
    base.update(cfg if isinstance(cfg, dict) else {})
    return base


def _missing_packages(requirement: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for pkg in requirement.get("required_python_packages", []) or []:
        if importlib.util.find_spec(str(pkg)) is None:
            missing.append(str(pkg))
    return missing


def _missing_binaries(requirement: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for binary in requirement.get("required_binaries", []) or []:
        if shutil.which(str(binary)) is None:
            missing.append(str(binary))
    return missing


def _missing_artifacts(requirement: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for artifact in requirement.get("required_model_artifacts", []) or []:
        path = Path(str(artifact))
        if not path.is_file():
            missing.append(str(path))
    return missing


def evaluate_adapter_requirements(config: dict[str, Any], adapter_set: str) -> dict[str, Any]:
    req = _merge_requirement(config, adapter_set)
    missing_packages = _missing_packages(req)
    missing_binaries = _missing_binaries(req)
    missing_artifacts = _missing_artifacts(req)
    missing = {
        "packages": missing_packages,
        "binaries": missing_binaries,
        "artifacts": missing_artifacts,
    }
    is_ready = not (missing_packages or missing_binaries or missing_artifacts)
    return {
        "adapter_id": req.get("adapter_id", adapter_set),
        "is_ready": is_ready,
        "missing": missing,
        "runtime_fallback_adapter": str(req.get("runtime_fallback_adapter", "default")),
    }
