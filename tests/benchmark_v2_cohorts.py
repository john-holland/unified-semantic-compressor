"""
V2 cohort benchmark with fallback and coverage metrics.

Usage:
  set PYTHONPATH=C:\\Users\\John\\unified-semantic-compressor;C:\\Users\\John\\Drawer 2\\Scripts
  python tests/benchmark_v2_cohorts.py --input "d:/Aleph/Downloads/Flight log.mp4"
"""

from __future__ import annotations

import argparse
import gc
from datetime import datetime, timezone
import importlib.util
import hashlib
import json
import time
from pathlib import Path

from unified_semantic_archiver.compressors.video_compressor import video_compress

def _default_models_dir() -> Path:
    return Path(r"C:\Users\John\Downloads")


def _resolve_model_paths(models_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    return (
        models_dir / "ffmpeg-master-latest-win64-gpl-shared" / "bin",
        models_dir / "blip-image-captioning-base",
        models_dir / "blip2-opt-2.7b",
        models_dir / "CogVideoX-2b",
        models_dir / "whisper-base",
        models_dir / "openai-whisper-base",
    )


def _is_hf_repo_id(value: str) -> bool:
    """Heuristic for HuggingFace repo ids like org/model."""
    if not value:
        return False
    if value.startswith(("http://", "https://", "./", "../")):
        return False
    if ":" in value or "\\" in value:
        return False
    parts = value.split("/")
    return len(parts) == 2 and all(parts)


def _is_blip2_local_complete(model_dir: Path) -> bool:
    """True when local BLIP2 directory appears complete enough to load."""
    if not model_dir.is_dir():
        return False
    if (model_dir / "model.safetensors").is_file():
        return True
    return (model_dir / "model-00001-of-00002.safetensors").is_file()


def _coverage(script_path: Path) -> dict[str, float]:
    if not script_path.is_file():
        return {"transcript_present": 0.0, "audio_effects_present": 0.0}
    text = script_path.read_text(encoding="utf-8", errors="ignore").lower()
    return {
        "transcript_present": 1.0 if "[transcript]" in text and len(text.strip()) > 0 else 0.0,
        "audio_effects_present": 1.0 if "[audio effects]" in text else 0.0,
    }


def _is_stub_cell(cell: dict) -> bool:
    return cell.get("script_backend") == "stub" and cell.get("t2v_backend") == "stub"


def _runtime_cost_units(cfg: dict, runtime_duration_sec: float) -> float:
    script_backend = str((cfg.get("script") or {}).get("backend", "stub"))
    t2v_backend = str((cfg.get("t2v") or {}).get("backend", "stub"))
    script_mult = 3.0 if script_backend == "whisper" else 1.0
    t2v_mult = 12.0 if t2v_backend in ("cogvideox", "cogvideo") else 1.0
    return float(runtime_duration_sec * script_mult * t2v_mult)


def _nearest_stub_for(cell_key: str, built: dict[str, dict]) -> str | None:
    parts = built[cell_key].get("matrix", {})
    preferred = (
        f"{parts.get('cohort')}|script=stub|t2v=stub|visual={parts.get('visual_backend')}|"
        f"lossless={'on' if parts.get('lossless') else 'off'}"
    )
    if preferred in built:
        return preferred
    fallback = [k for k, v in built.items() if _is_stub_cell(v.get("matrix", {}))]
    if not fallback:
        return None
    return fallback[0]


def _check_backend_availability(cfg: dict) -> str | None:
    script_backend = str((cfg.get("script") or {}).get("backend", "stub"))
    visual_backend = str((cfg.get("script") or {}).get("visual_backend", "none"))
    visual_model = str((cfg.get("script") or {}).get("visual_model") or "").strip()
    t2v_cfg = cfg.get("t2v") or {}
    t2v_backend = str(t2v_cfg.get("backend", "stub"))
    ffmpeg_path = (cfg.get("audio") or {}).get("ffmpeg_path")
    if ffmpeg_path and not Path(str(ffmpeg_path)).exists():
        return f"ffmpeg path unavailable ({ffmpeg_path})"
    if visual_backend in ("blip", "blip2"):
        if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
            return f"visual backend {visual_backend} unavailable (transformers/torch missing)"
        if importlib.util.find_spec("PIL") is None:
            return f"visual backend {visual_backend} unavailable (Pillow missing)"
        if visual_model and not _is_hf_repo_id(visual_model):
            model_path = Path(visual_model)
            if visual_backend == "blip2":
                if not _is_blip2_local_complete(model_path):
                    return (
                        f"visual backend {visual_backend} model path unavailable or incomplete "
                        f"({visual_model})"
                    )
            elif not model_path.exists():
                return f"visual backend {visual_backend} model path unavailable ({visual_model})"
    if script_backend == "whisper":
        if importlib.util.find_spec("whisper") is None:
            return "script backend whisper unavailable (package 'whisper' missing)"
        script_cfg = cfg.get("script") or {}
        whisper_mp = script_cfg.get("model_path")
        if whisper_mp:
            p = Path(str(whisper_mp))
            model_name = script_cfg.get("model", "base")
            if p.suffix == ".pt":
                valid = p.exists()
            else:
                valid = (p / f"{model_name}.pt").exists()
            if not valid:
                return f"script backend whisper model_path unavailable ({whisper_mp})"
    if t2v_backend in ("cogvideox", "cogvideo"):
        if importlib.util.find_spec("torch") is None or importlib.util.find_spec("diffusers") is None:
            return "t2v backend cogvideox unavailable (torch/diffusers missing)"
        if not (t2v_cfg.get("model_id") or t2v_cfg.get("model_path")):
            return "t2v backend cogvideox unavailable (model_id/model_path not configured)"
        mp = t2v_cfg.get("model_path")
        if mp and not Path(str(mp)).exists():
            return f"t2v backend cogvideox unavailable (model_path not found: {mp})"
    return None


def _write_markdown_report(report: dict, markdown_path: Path) -> None:
    lines = [
        "# V2 Cohort Comparison Report",
        "",
        f"Source JSON: `{report.get('json_path', '')}`",
        "",
        f"Input clip: `{report['input_path']}`",
        f"Input bytes: `{report['input_bytes']:,}`",
        "",
        "## Matrix summary",
        "",
        f"- Matrix cardinality: `{report.get('matrix_cardinality', 0)}`",
        f"- Success cells: `{report.get('matrix_stats', {}).get('success_count', 0)}`",
        f"- Failed cells: `{report.get('matrix_stats', {}).get('failure_count', 0)}`",
        f"- Skipped cells: `{report.get('matrix_stats', {}).get('skipped_count', 0)}`",
        "",
        "## Matrix cells",
        "",
        "| Matrix key | Status | Effective adapter | Ratio | Runtime (s) | Cost units | Closest stub |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for name, payload in report["matrix_cells"].items():
        rt = payload.get("runtime", {}) or {}
        links = payload.get("links", {}) or {}
        lines.append(
            "| `{name}` | `{status}` | `{adapter}` | {ratio:.5f}x | {runtime:.3f} | {cost:.3f} | `{stub}` |".format(
                name=name,
                status=payload.get("execution_status", "unknown"),
                adapter=payload.get("adapter_set_effective"),
                ratio=float(payload.get("ratio_total_vs_input", 0.0)),
                runtime=float(rt.get("runtime_duration_sec", 0.0)),
                cost=float(rt.get("estimated_compute_cost_units", 0.0)),
                stub=links.get("closest_stub_cohort"),
            )
        )
    failures = [(k, v.get("failure_reason", "")) for k, v in report["matrix_cells"].items() if v.get("execution_status") == "failed"]
    skipped = [(k, v.get("failure_reason", "")) for k, v in report["matrix_cells"].items() if v.get("execution_status") == "skipped"]
    if failures:
        lines.extend(["", "## Failed cells", ""])
        for key, reason in failures:
            lines.append(f"- `{key}`: {reason}")
    if skipped:
        lines.extend(["", "## Skipped cells", ""])
        for key, reason in skipped:
            lines.append(f"- `{key}`: {reason}")

    rollups = report.get("matrix_rollups", {})
    lines.extend(["", "## Runtime/cost rollups", ""])
    for label in ("by_script_backend", "by_t2v_backend", "by_visual_backend", "by_lossless"):
        lines.append(f"- `{label}`: `{json.dumps(rollups.get(label, {}), sort_keys=True)}`")
    lines.extend(
        [
            "",
            "## JSON 2.0 links",
            "",
            "- Per matrix cell: `matrix_cells.<matrix_key>.links.closest_stub_cohort`, `closest_stub_result_path`, `closest_stub_report_path`",
            "- Top-level: `comparisons[]` relation objects for cohort -> closest stub",
            "",
            "## Portfolio runtime",
            "",
            "- `portfolio.runtime.total_duration_sec` reports end-to-end matrix runtime.",
            "- `portfolio.runtime.per_cell_duration_sec` reports run duration per matrix cell.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def _build_matrix_cells(
    base_cohorts: dict[str, dict],
    *,
    ffmpeg_dir: Path,
    blip_model: Path,
    blip2_model_ref: str,
    cogvideo_model: Path,
    whisper_model: Path,
    audio_caption_model: Path,
    visual_grid: int,
) -> list[tuple[str, dict, dict]]:
    script_backends = ["stub", "whisper"]
    t2v_backends = ["stub", "cogvideox"]
    visual_backends = ["blip", "blip2"]
    lossless_options = [False, True]
    matrix: list[tuple[str, dict, dict]] = []
    for cohort_name, base_cfg in base_cohorts.items():
        for script_backend in script_backends:
            for t2v_backend in t2v_backends:
                for visual_backend in visual_backends:
                    for lossless in lossless_options:
                        key = (
                            f"{cohort_name}|script={script_backend}|t2v={t2v_backend}|"
                            f"visual={visual_backend}|lossless={'on' if lossless else 'off'}"
                        )
                        script_overrides: dict = {
                            "backend": script_backend,
                            "visual_backend": visual_backend,
                            "visual_model": str(blip2_model_ref if visual_backend == "blip2" else blip_model),
                            "visual_interval_sec": 2.0,
                            "visual_max_frames": 8,
                            "visual_grid": int(visual_grid),
                        }
                        if script_backend == "whisper" and whisper_model.exists():
                            script_overrides["model_path"] = str(whisper_model)
                        audio_caption_overrides: dict = {}
                        if audio_caption_model.exists():
                            audio_caption_overrides["model_path"] = str(audio_caption_model)
                        cfg = _merge(
                            base_cfg,
                            {
                                "audio": {"ffmpeg_path": str(ffmpeg_dir)},
                                "script": script_overrides,
                                "t2v": {
                                    "backend": t2v_backend,
                                    "model_path": str(cogvideo_model) if t2v_backend in ("cogvideox", "cogvideo") else None,
                                    "num_inference_steps": 2,
                                    "num_frames": 8,
                                    "fps": 4,
                                    "guidance_scale": 4.0,
                                },
                                "diff": {"lossless": bool(lossless), "enabled": True},
                            },
                        )
                        if audio_caption_overrides:
                            ac = (cfg.get("audio_captioning") or {}).copy()
                            ac.update(audio_caption_overrides)
                            cfg["audio_captioning"] = ac
                        dims = {
                            "cohort": cohort_name,
                            "script_backend": script_backend,
                            "t2v_backend": t2v_backend,
                            "visual_backend": visual_backend,
                            "lossless": bool(lossless),
                        }
                        matrix.append((key, cfg, dims))
    return matrix


def _rollup(values: dict[str, list[tuple[float, float]]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key, rows in values.items():
        count = len(rows)
        out[key] = {
            "count": float(count),
            "avg_runtime_sec": (sum(r for r, _ in rows) / count) if count else 0.0,
            "sum_cost_units": sum(c for _, c in rows),
        }
    return out


def _cell_out_dir(results_root: Path | None, matrix_key: str, index: int) -> Path:
    if results_root is None:
        import tempfile

        return Path(tempfile.mkdtemp(prefix="v2_matrix_"))
    digest = hashlib.sha1(matrix_key.encode("utf-8")).hexdigest()[:12]
    out = results_root / f"cell_{index:03d}_{digest}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def run(
    input_path: Path,
    *,
    results_root: Path | None = None,
    models_dir: Path | None = None,
    blip2_model_id: str | None = None,
    visual_grid: int = 2,
) -> dict:
    base_cohorts = {
        "default_v2": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"visual_backend": "none"},
            "diff": {"enabled": True, "quality": 6},
            "transcript": {"policy": "whisper_preferred"},
            "audio_captioning": {"enabled": True, "mode": "speech_gap_only"},
            "minimization": {"enabled": True, "pipeline": {"adapter_set": "default"}},
        },
        "cairn_residual_v2": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"visual_backend": "none"},
            "diff": {"enabled": True, "quality": 6},
            "transcript": {"policy": "whisper_preferred"},
            "audio_captioning": {"enabled": True, "mode": "speech_gap_only"},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "cairn_residual_v1"},
                "cairn": {"enabled": True, "write_debug_json": False, "emit_resultant_audio": False},
            },
        },
        "planar_hyperplane_v2": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"visual_backend": "none"},
            "diff": {"enabled": True, "quality": 6},
            "transcript": {"policy": "whisper_preferred"},
            "audio_captioning": {"enabled": True, "mode": "speech_gap_only"},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "planar_hyperplane_v1"},
                "cairn": {"enabled": True, "write_debug_json": False, "emit_resultant_audio": False},
            },
        },
        "audio_captioning_v1": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"visual_backend": "none"},
            "diff": {"enabled": True, "quality": 6},
            "transcript": {"policy": "whisper_preferred"},
            "audio_captioning": {"enabled": True, "mode": "always"},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "audio_captioning_v1"},
                "adapter_requirements": {
                    "audio_captioning_v1": {
                        "required_python_packages": ["transformers", "torch"],
                        "runtime_fallback_adapter": "default",
                    }
                },
            },
        },
    }

    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    md = models_dir if models_dir is not None else _default_models_dir()
    ffmpeg_dir, blip_model, blip2_model, cogvideo_model, whisper_model, audio_caption_model = _resolve_model_paths(md)
    blip2_model_ref = str(blip2_model)
    if blip2_model_id:
        blip2_model_ref = blip2_model_id
    elif not _is_blip2_local_complete(blip2_model):
        # Use Hub id fallback when local BLIP2 path is incomplete/missing.
        blip2_model_ref = "Salesforce/blip2-opt-2.7b"
    cells = _build_matrix_cells(
        base_cohorts,
        ffmpeg_dir=ffmpeg_dir,
        blip_model=blip_model,
        blip2_model_ref=blip2_model_ref,
        cogvideo_model=cogvideo_model,
        whisper_model=whisper_model,
        audio_caption_model=audio_caption_model,
        visual_grid=visual_grid,
    )
    report = {
        "schema_version": "2.0",
        "input_path": str(input_path),
        "input_bytes": input_path.stat().st_size,
        "matrix_dimensions": {
            "cohorts": list(base_cohorts.keys()),
            "script_backend": ["stub", "whisper"],
            "t2v_backend": ["stub", "cogvideox"],
            "visual_backend": ["blip", "blip2"],
            "visual_grid": [int(visual_grid)],
            "diff_lossless": [False, True],
            "strict_fail": True,
        },
        "matrix_cardinality": len(cells),
        "portfolio": {
            "runtime": {
                "run_started_at": started,
            }
        },
        "results_root": str(results_root) if results_root is not None else None,
        "adapter_config_matrix": {},
        "matrix_cells": {},
        "comparisons": [],
    }
    for index, (key, cfg, dims) in enumerate(cells):
        report["adapter_config_matrix"][key] = {
            "script_backend": dims["script_backend"],
            "t2v_backend": dims["t2v_backend"],
            "visual_backend": dims["visual_backend"],
            "pipeline_adapter_set_configured": str((cfg.get("minimization") or {}).get("pipeline", {}).get("adapter_set", "default")),
            "is_stub_variant": dims["script_backend"] == "stub" and dims["t2v_backend"] == "stub",
            "lossless": dims["lossless"],
        }
        run_started_at = datetime.now(timezone.utc).isoformat()
        run_t0 = time.perf_counter()
        out = _cell_out_dir(results_root, key, index)
        fail_reason = _check_backend_availability(cfg)
        status = "ok"
        res = {"unique_chunk_refs": []}
        files: dict[str, int] = {}
        diag: dict = {}
        if fail_reason:
            status = "skipped" if dims.get("visual_backend") == "blip2" else "failed"
        else:
            try:
                res = video_compress(input_path, out, config=cfg)
                files = {p.name: p.stat().st_size for p in out.iterdir() if p.is_file()}
                mr = out / "minimization_report.json"
                if mr.is_file():
                    try:
                        diag = json.loads(mr.read_text(encoding="utf-8")).get("diagnostics", {})
                    except Exception:
                        diag = {}
            except Exception as exc:
                status = "skipped" if dims.get("visual_backend") == "blip2" else "failed"
                fail_reason = str(exc)
            finally:
                # Keep memory pressure low between cells to reduce loader instability on Windows.
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
        run_duration_sec = max(0.0, time.perf_counter() - run_t0)
        run_finished_at = datetime.now(timezone.utc).isoformat()
        report["matrix_cells"][key] = {
            "matrix_key": key,
            "matrix": dims,
            "execution_status": status,
            "failure_reason": fail_reason,
            "out_dir": str(out),
            "stored_total_bytes": sum(files.values()),
            "ratio_total_vs_input": sum(files.values()) / report["input_bytes"],
            "unique_chunk_refs_count": len(res.get("unique_chunk_refs") or []),
            "coverage": _coverage(out / "script.txt"),
            "adapter_set_effective": diag.get("adapter_set"),
            "adapter_requirements": diag.get("adapter_requirements", {}),
            "runtime": {
                "run_started_at": run_started_at,
                "run_finished_at": run_finished_at,
                "runtime_duration_sec": run_duration_sec,
                "estimated_compute_cost_units": _runtime_cost_units(cfg, run_duration_sec),
                "cost_basis": {
                    "script_backend": str((cfg.get("script") or {}).get("backend", "stub")),
                    "t2v_backend": str((cfg.get("t2v") or {}).get("backend", "stub")),
                },
            },
            "files": files,
        }
    # JSON 2.0 style links and top-level comparison graph.
    success_count = 0
    failure_count = 0
    skipped_count = 0
    for name, payload in report["matrix_cells"].items():
        if payload.get("execution_status") == "ok":
            success_count += 1
        elif payload.get("execution_status") == "skipped":
            skipped_count += 1
        else:
            failure_count += 1
        nearest = _nearest_stub_for(name, report["matrix_cells"])
        nearest_payload = report["matrix_cells"].get(nearest, {}) if nearest else {}
        links = {
            "closest_stub_cohort": nearest,
            "closest_stub_result_path": str(Path(nearest_payload.get("out_dir", "")) / "resultant.mp4") if nearest else None,
            "closest_stub_report_path": str(Path(nearest_payload.get("out_dir", "")) / "minimization_report.json") if nearest else None,
        }
        payload["links"] = links
        if nearest and payload.get("execution_status") == "ok":
            report["comparisons"].append(
                {
                    "from_cohort": name,
                    "to_stub_cohort": nearest,
                    "relation": "closest_stub",
                    "delta_ratio": float(payload.get("ratio_total_vs_input", 0.0))
                    - float(nearest_payload.get("ratio_total_vs_input", 0.0)),
                    "delta_runtime_sec": float(payload.get("runtime", {}).get("runtime_duration_sec", 0.0))
                    - float(nearest_payload.get("runtime", {}).get("runtime_duration_sec", 0.0)),
                    "delta_ref_count": int(payload.get("unique_chunk_refs_count", 0))
                    - int(nearest_payload.get("unique_chunk_refs_count", 0)),
                    "stub_result_path": links["closest_stub_result_path"],
                    "stub_report_path": links["closest_stub_report_path"],
                }
            )
    report["matrix_stats"] = {
        "success_count": success_count,
        "failure_count": failure_count,
        "skipped_count": skipped_count,
    }

    by_script: dict[str, list[tuple[float, float]]] = {}
    by_t2v: dict[str, list[tuple[float, float]]] = {}
    by_visual: dict[str, list[tuple[float, float]]] = {}
    by_lossless: dict[str, list[tuple[float, float]]] = {}
    for payload in report["matrix_cells"].values():
        if payload.get("execution_status") != "ok":
            continue
        rt = float(payload.get("runtime", {}).get("runtime_duration_sec", 0.0))
        cost = float(payload.get("runtime", {}).get("estimated_compute_cost_units", 0.0))
        dims = payload.get("matrix", {})
        by_script.setdefault(str(dims.get("script_backend")), []).append((rt, cost))
        by_t2v.setdefault(str(dims.get("t2v_backend")), []).append((rt, cost))
        by_visual.setdefault(str(dims.get("visual_backend")), []).append((rt, cost))
        by_lossless.setdefault(str(bool(dims.get("lossless"))), []).append((rt, cost))
    report["matrix_rollups"] = {
        "by_script_backend": _rollup(by_script),
        "by_t2v_backend": _rollup(by_t2v),
        "by_visual_backend": _rollup(by_visual),
        "by_lossless": _rollup(by_lossless),
    }
    finished = datetime.now(timezone.utc).isoformat()
    total_duration_sec = max(0.0, time.perf_counter() - t0)
    report["portfolio"]["runtime"]["run_finished_at"] = finished
    report["portfolio"]["runtime"]["total_duration_sec"] = total_duration_sec
    report["portfolio"]["runtime"]["per_cell_duration_sec"] = {
        name: float(payload.get("runtime", {}).get("runtime_duration_sec", 0.0))
        for name, payload in report["matrix_cells"].items()
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path(r"d:\Aleph\Downloads\v2_cohort_report.json"))
    p.add_argument("--results-root", type=Path, default=None)
    p.add_argument(
        "--blip2-model-id",
        type=str,
        default=None,
        help="Optional HF model id fallback for BLIP2 (e.g. Salesforce/blip2-opt-2.7b)",
    )
    p.add_argument(
        "--visual-grid",
        type=int,
        default=2,
        help="Visual caption frame grid size: 1 (whole), 2 (2x2), 3 (3x3).",
    )
    p.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="Directory containing ffmpeg, blip, blip2, CogVideoX, whisper-base, openai-whisper-base (default: C:\\Users\\John\\Downloads)",
    )
    args = p.parse_args()
    if args.results_root is not None:
        args.results_root.mkdir(parents=True, exist_ok=True)
    report = run(
        args.input,
        results_root=args.results_root,
        models_dir=args.models_dir,
        blip2_model_id=args.blip2_model_id,
        visual_grid=max(1, min(3, int(args.visual_grid))),
    )
    report["json_path"] = str(args.out)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_out = args.out.with_suffix(".md")
    _write_markdown_report(report, md_out)
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
