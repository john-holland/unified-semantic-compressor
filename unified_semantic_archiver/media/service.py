from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from unified_semantic_archiver.media.minimization import MinimizationContext, run_minimization

log = logging.getLogger("unified_semantic_archiver.media.service")


class MediaServiceUnavailable(RuntimeError):
    """Raised when media primitives are unavailable in the runtime."""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class UscMediaService:
    """
    USC media service wrapper used by Continuum.
    Wraps video_storage_tool primitives behind a stable callable surface.
    """

    def __init__(
        self,
        *,
        storage_root: Path | None = None,
        config_path: Path | None = None,
        settings_path: Path | None = None,
    ) -> None:
        self.storage_root = Path(
            storage_root
            or os.environ.get("USC_MEDIA_STORAGE_ROOT")
            or (Path.cwd() / "media_storage")
        )
        self.config_path = Path(
            config_path
            or os.environ.get("USC_MEDIA_CONFIG_PATH")
            or (Path.cwd() / "media_config.yaml")
        )
        self.settings_path = Path(
            settings_path
            or os.environ.get("USC_MEDIA_SETTINGS_PATH")
            or (Path.cwd() / "media_settings.json")
        )
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._store_progress: dict[str, dict[str, Any]] = {}
        self._stream_cache = None
        self._t2v_download_status: dict[str, str] = {
            "status": "idle",
            "message": "",
            "model_id": "",
        }

    def _import_video_storage_tool(self):
        try:
            from video_storage_tool import __main__ as cli
            from video_storage_tool.media_utils import get_image_format, is_image_input
            from video_storage_tool.reconstitute import reconstitute
            from video_storage_tool.stream_cache import StreamCache
        except ImportError as exc:
            raise MediaServiceUnavailable(
                "video_storage_tool is required for USC media runtime parity."
            ) from exc
        return cli, is_image_input, get_image_format, reconstitute, StreamCache

    def _job_key(self, tenant_id: str, job_id: str) -> str:
        return f"{tenant_id}:{job_id}"

    def _tenant_root(self, tenant_id: str) -> Path:
        root = self.storage_root / tenant_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _storage_dir(self, tenant_id: str, job_id: str) -> Path:
        return self._tenant_root(tenant_id) / job_id

    def _config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {}
        if self.config_path.is_file():
            try:
                import yaml

                cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
            except Exception:
                cfg = {}
        if self.settings_path.is_file():
            try:
                overrides = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(overrides, dict):
                    _deep_merge(cfg, overrides)
            except Exception:
                pass
        if cfg.get("device"):
            cfg.setdefault("t2v", {})["device"] = cfg.get("device")
        return cfg

    def _get_stream_cache(self):
        cfg = self._config()
        sc = cfg.get("stream_cache") or {}
        if not sc.get("enabled"):
            return None
        if self._stream_cache is None:
            _, _, _, _, stream_cache_cls = self._import_video_storage_tool()
            cache_dir = Path(sc.get("directory", self.storage_root / "stream_cache"))
            budget_gb = float(sc.get("budget_gb", 10.0))
            self._stream_cache = stream_cache_cls(cache_dir, int(budget_gb * (1024**3)))
        return self._stream_cache

    def _run_store(
        self,
        *,
        input_path: Path,
        out_dir: Path,
        job_id: str,
        tenant_id: str,
        force_script: bool = False,
        input_image_format: str | None = None,
        source_image: Path | None = None,
    ) -> None:
        key = self._job_key(tenant_id, job_id)
        cli, _, _, _, _ = self._import_video_storage_tool()

        def progress_cb(phase: str, progress: float, message: str) -> None:
            self._store_progress[key] = {
                "phase": phase,
                "progress": progress,
                "message": message,
            }

        try:
            cfg = self._config()
            cli.run_store(
                input_path,
                out_dir,
                config=cfg,
                t2v_backend=cfg.get("t2v", {}).get("backend", "stub"),
                t2v_model_path=cfg.get("t2v", {}).get("model_path"),
                t2v_model_id=cfg.get("t2v", {}).get("model_id"),
                script_backend=cfg.get("script", {}).get("backend", "whisper"),
                progress_callback=progress_cb,
                force_script=force_script,
                input_image_format=input_image_format,
                source_image=source_image,
            )
            mini_result = run_minimization(
                MinimizationContext(
                    video_path=input_path,
                    resultant_path=out_dir / "resultant.mp4",
                    diff_path=(out_dir / "diff.mkv") if (out_dir / "diff.mkv").is_file() else ((out_dir / "diff.ogv") if (out_dir / "diff.ogv").is_file() else None),
                    script_path=out_dir / "script.txt",
                    out_dir=out_dir,
                    grid_size=int((cfg.get("minimization", {}).get("grid_size") or cfg.get("script", {}).get("visual_grid") or 2)),
                    config=cfg,
                    source="runtime",
                    tenant_id=tenant_id,
                    job_id=job_id,
                    video_style_description=str(cfg.get("script", {}).get("video_style_description", "")),
                )
            )
            if mini_result.diagnostics.get("enabled"):
                self._attach_minimization_metadata(out_dir, mini_result.unique_chunk_refs, mini_result.diagnostics)
        finally:
            self._store_progress.pop(key, None)

    def _attach_minimization_metadata(
        self,
        out_dir: Path,
        unique_chunk_refs: list[str],
        diagnostics: dict[str, Any],
    ) -> None:
        manifest_path = out_dir / "manifest.json"
        payload: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    payload = raw
            except Exception:
                payload = {}
        payload["minimization"] = {
            "enabled": True,
            "unique_chunk_refs": unique_chunk_refs,
            "diagnostics": diagnostics,
        }
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def store(self, input_path: Path, tenant_id: str, settings: dict | None = None) -> dict[str, Any]:
        cli, is_image_input, get_image_format, _, _ = self._import_video_storage_tool()
        job_id = str(uuid.uuid4())
        st = self._storage_dir(tenant_id, job_id)
        st.mkdir(parents=True, exist_ok=True)
        input_video = st / "input.mp4"
        input_image_format = None
        source_image_path = None

        if settings:
            self.update_settings(settings)

        if is_image_input(input_path):
            input_image_format = get_image_format(input_path)
            ext = "jpg" if input_image_format == "jpeg" else input_image_format
            source_image_path = st / f"source_image.{ext}"
            shutil.copy2(input_path, source_image_path)
            ffmpeg_path = self._config().get("audio", {}).get("ffmpeg_path")
            cli._image_to_video(source_image_path, input_video, ffmpeg_path)
        else:
            shutil.copy2(input_path, input_video)

        threading.Thread(
            target=self._run_store,
            kwargs={
                "input_path": input_video,
                "out_dir": st,
                "job_id": job_id,
                "tenant_id": tenant_id,
                "input_image_format": input_image_format,
                "source_image": source_image_path,
            },
            daemon=True,
        ).start()
        return {"id": job_id, "status": "processing"}

    def list_jobs(self, tenant_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for p in sorted(self._tenant_root(tenant_id).iterdir(), key=lambda x: x.name):
            if not p.is_dir() or not (p / "input.mp4").exists():
                continue
            status = "ready" if (p / "manifest.json").exists() else "incomplete"
            items.append({"id": p.name, "status": status})
        return items

    def get_job_status(self, job_id: str, tenant_id: str) -> dict[str, Any]:
        st = self._storage_dir(tenant_id, job_id)
        if not st.is_dir():
            raise FileNotFoundError(job_id)
        manifest_path = st / "manifest.json"
        if manifest_path.exists():
            return {
                "status": "ready",
                "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
            }
        prog = self._store_progress.get(self._job_key(tenant_id, job_id), {})
        result: dict[str, Any] = {"status": "processing"}
        if prog:
            result.update(prog)
        return result

    def retry_store(
        self,
        job_id: str,
        tenant_id: str,
        force_script: bool = False,
    ) -> dict[str, Any]:
        st = self._storage_dir(tenant_id, job_id)
        input_path = st / "input.mp4"
        if not st.is_dir() or not input_path.is_file():
            raise FileNotFoundError(job_id)
        if self._store_progress.get(self._job_key(tenant_id, job_id)):
            raise RuntimeError("Job already in progress")

        input_image_format = None
        source_image = None
        for p in st.glob("source_image.*"):
            if p.is_file():
                source_image = p
                input_image_format = p.suffix.lstrip(".").lower().replace("jpg", "jpeg")
                break

        threading.Thread(
            target=self._run_store,
            kwargs={
                "input_path": input_path,
                "out_dir": st,
                "job_id": job_id,
                "tenant_id": tenant_id,
                "force_script": force_script,
                "input_image_format": input_image_format,
                "source_image": source_image,
            },
            daemon=True,
        ).start()
        return {"id": job_id, "status": "processing"}

    def _resolve_stream_path(self, job_id: str, tenant_id: str, use_original: bool) -> Path:
        _, _, _, reconstitute, _ = self._import_video_storage_tool()
        st = self._storage_dir(tenant_id, job_id)
        if not st.is_dir() or not (st / "manifest.json").exists():
            raise FileNotFoundError(job_id)

        out_name = "reconstituted_original.mp4" if use_original else "reconstituted.mp4"
        out_path = st / out_name
        cache = self._get_stream_cache()
        if cache is not None:
            cached = cache.get(job_id, use_original)
            if cached is not None and cached.is_file():
                return cached
        if not out_path.is_file():
            reconstitute(
                st,
                out_path,
                use_diff=use_original,
                ffmpeg_path=self._config().get("audio", {}).get("ffmpeg_path"),
            )
        if cache is not None:
            return cache.put(job_id, use_original, out_path)
        return out_path

    def reconstitute(self, job_id: str, tenant_id: str, use_original: bool) -> dict[str, Any]:
        path = self._resolve_stream_path(job_id, tenant_id, use_original)
        return {
            "path": str(path),
            "out_path": "reconstituted_original.mp4" if use_original else "reconstituted.mp4",
        }

    def stream_info(self, job_id: str, tenant_id: str, use_original: bool) -> dict[str, Any]:
        path = self._resolve_stream_path(job_id, tenant_id, use_original)
        return {
            "content_length": path.stat().st_size,
            "filename": path.name,
            "original": use_original,
            "path": str(path),
        }

    def open_stream(
        self,
        job_id: str,
        tenant_id: str,
        use_original: bool,
        byte_range: tuple[int, int] | None,
    ) -> dict[str, Any]:
        path = self._resolve_stream_path(job_id, tenant_id, use_original)
        total = path.stat().st_size
        start, end = (0, total - 1) if byte_range is None else byte_range
        if start < 0 or end < start or start >= total:
            raise ValueError("Invalid byte range")
        end = min(end, total - 1)
        return {
            "path": path,
            "start": start,
            "end": end,
            "total": total,
            "content_length": end - start + 1,
            "partial": byte_range is not None,
        }

    def get_settings(self) -> dict[str, Any]:
        cfg = self._config()
        sc = cfg.get("stream_cache") or {}
        minimization = cfg.get("minimization") or {}
        mini_pipeline = minimization.get("pipeline") or {}
        mini_model = minimization.get("model") or {}
        mini_quadtree = minimization.get("quadtree") or {}
        mini_cairn = minimization.get("cairn") or {}
        mini_hyperplane = minimization.get("hyperplane") or {}
        mini_exp = minimization.get("experiments") or {}
        mini_codec = minimization.get("codec") or {}
        mini_req = minimization.get("adapter_requirements") or {}
        transcript_cfg = cfg.get("transcript") or {}
        audio_caption_cfg = cfg.get("audio_captioning") or {}
        return {
            "device": cfg.get("device") or cfg.get("t2v", {}).get("device") or "auto",
            "t2v": {
                "backend": cfg.get("t2v", {}).get("backend", "stub"),
                "model_id": cfg.get("t2v", {}).get("model_id") or "",
                "model_path": cfg.get("t2v", {}).get("model_path") or "",
            },
            "script": {
                "model": cfg.get("script", {}).get("model", "base"),
                "visual_backend": cfg.get("script", {}).get("visual_backend", "blip"),
                "visual_interval_sec": cfg.get("script", {}).get("visual_interval_sec", 1.0),
                "visual_max_frames": cfg.get("script", {}).get("visual_max_frames", 60),
                "visual_grid": cfg.get("script", {}).get("visual_grid", 2),
                "video_style_description": str(cfg.get("script", {}).get("video_style_description", "")),
            },
            "transcript": {
                "policy": str(transcript_cfg.get("policy", "whisper_preferred")),
            },
            "audio_captioning": {
                "enabled": bool(audio_caption_cfg.get("enabled", True)),
                "mode": str(audio_caption_cfg.get("mode", "speech_gap_only")),
                "model_id": str(audio_caption_cfg.get("model_id", "openai/whisper-base")),
                "max_tokens": int(audio_caption_cfg.get("max_tokens", 64)),
            },
            "audio": {
                "ffmpeg_path": cfg.get("audio", {}).get("ffmpeg_path") or "",
            },
            "store": {
                "loss_coefficient": float(cfg.get("store", {}).get("loss_coefficient", 0.0)),
            },
            "diff": {
                "enabled": bool(cfg.get("diff", {}).get("enabled", True)),
                "lossless": bool(cfg.get("diff", {}).get("lossless", cfg.get("store", {}).get("loss_coefficient", 0.0) == 0)),
                "quality": int(cfg.get("diff", {}).get("quality", 6)),
            },
            "stream_cache": {
                "enabled": bool(sc.get("enabled", False)),
                "budget_gb": float(sc.get("budget_gb", 10.0)),
                "directory": str(sc.get("directory", "stream_cache")),
            },
            "minimization": {
                "enabled": bool(minimization.get("enabled", False)),
                "threshold": float(minimization.get("threshold", 0.55)),
                "max_refs": int(minimization.get("max_refs", 128)),
                "grid_size": int(minimization.get("grid_size", 2)),
                "pipeline": {
                    "adapter_set": str(mini_pipeline.get("adapter_set", "minimization-usc-adapter")),
                    "stages": {
                        "extract": str((mini_pipeline.get("stages") or {}).get("extract", "default")),
                        "tokenize": str((mini_pipeline.get("stages") or {}).get("tokenize", "default")),
                        "bucket": str((mini_pipeline.get("stages") or {}).get("bucket", "default")),
                        "score": str((mini_pipeline.get("stages") or {}).get("score", "default")),
                        "select": str((mini_pipeline.get("stages") or {}).get("select", "default")),
                        "persist": str((mini_pipeline.get("stages") or {}).get("persist", "default")),
                    },
                },
                "model": {
                    "path_json": str(mini_model.get("path_json", "")),
                    "path_joblib": str(mini_model.get("path_joblib", "")),
                    "format_preference": str(mini_model.get("format_preference", "json_first")),
                    "glm": {
                        "enabled": bool((mini_model.get("glm") or {}).get("enabled", False)),
                        "family": str((mini_model.get("glm") or {}).get("family", "binomial")),
                        "link": str((mini_model.get("glm") or {}).get("link", "logit")),
                        "l1_alpha": float((mini_model.get("glm") or {}).get("l1_alpha", 0.0)),
                        "l2_alpha": float((mini_model.get("glm") or {}).get("l2_alpha", 0.0)),
                        "temperature": float((mini_model.get("glm") or {}).get("temperature", 1.0)),
                    },
                    "feature_order": mini_model.get(
                        "feature_order",
                        [
                            "token_density",
                            "token_entropy",
                            "bucket_depth_norm",
                            "temporal_position",
                            "diff_size_norm",
                            "style_description_density",
                            "style_alignment_ratio",
                            "plane_id",
                            "plane_transition_rate",
                            "stone_entropy",
                            "stone_transition_rate",
                            "pitch_delta_norm",
                            "energy_slope",
                            "dominant_stone_persistence",
                        ],
                    ),
                },
                "quadtree": {
                    "max_depth": int(mini_quadtree.get("max_depth", 2)),
                },
                "cairn": {
                    "enabled": bool(mini_cairn.get("enabled", True)),
                    "max_depth": int(mini_cairn.get("max_depth", 3)),
                    "write_debug_json": bool(mini_cairn.get("write_debug_json", False)),
                    "emit_resultant_audio": bool(mini_cairn.get("emit_resultant_audio", False)),
                },
                "codec": {
                    "residual_enabled": bool(mini_codec.get("residual_enabled", True)),
                    "residual_schema": str(mini_codec.get("residual_schema", "cairn_residual_v1")),
                    "residual_deadzone_q": int(mini_codec.get("residual_deadzone_q", 2)),
                },
                "hyperplane": {
                    "intercept": float(mini_hyperplane.get("intercept", -1.8)),
                    "coefficients": mini_hyperplane.get("coefficients", {}),
                    "piecewise_by_plane": mini_hyperplane.get("piecewise_by_plane", {}),
                },
                "experiments": {
                    "enabled": bool(mini_exp.get("enabled", False)),
                    "cohort_key": str(mini_exp.get("cohort_key", "hash")),
                    "portfolio_percent_min": int(mini_exp.get("portfolio_percent_min", 0)),
                    "cohorts": mini_exp.get(
                        "cohorts",
                        {
                            "default_v2": {"adapter_set": "default", "percent": 40},
                            "cairn_residual_v2": {"adapter_set": "cairn_residual_v1", "percent": 25},
                            "planar_hyperplane_v2": {"adapter_set": "planar_hyperplane_v1", "percent": 20},
                            "audio_captioning_v1": {"adapter_set": "audio_captioning_v1", "percent": 15},
                        },
                    ),
                },
                "adapter_requirements": mini_req,
            },
        }

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        existing: dict[str, Any] = {}
        if self.settings_path.is_file():
            try:
                payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    existing = payload
            except Exception:
                existing = {}
        _deep_merge(existing, updates)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        self._stream_cache = None
        return {"ok": True}

    def _run_t2v_download(self, model_id: str) -> None:
        self._t2v_download_status = {
            "status": "downloading",
            "message": f"Downloading {model_id}",
            "model_id": model_id,
        }
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=model_id, resume_download=True)
            self._t2v_download_status = {
                "status": "done",
                "message": f"Downloaded {model_id}",
                "model_id": model_id,
            }
        except Exception as exc:
            self._t2v_download_status = {
                "status": "error",
                "message": str(exc),
                "model_id": model_id,
            }

    def start_t2v_download(self) -> dict[str, Any]:
        cfg = self._config()
        model_id = str((cfg.get("t2v") or {}).get("model_id") or "").strip()
        if not model_id:
            raise ValueError("No t2v.model_id configured")
        if self._t2v_download_status.get("status") == "downloading":
            raise RuntimeError("Download already in progress")
        threading.Thread(target=self._run_t2v_download, args=(model_id,), daemon=True).start()
        return {"ok": True, "model_id": model_id}

    def get_t2v_download_status(self) -> dict[str, Any]:
        return dict(self._t2v_download_status)
