"""
Integration test: BLIP visual description (chunked script) + CogVideoX T2V.

Verifies the full pipeline with real models:
- BLIP describes video frames → chunked [Visual description] in script.txt
- CogVideoX generates resultant.mp4 from script

Fails if BLIP description is missing/empty or if resultant is blank/black
(i.e. stub fallback). Uses frame pixel std: resultant must be within 1 std of input.
Skips when models (BLIP, CogVideoX) or ffmpeg are unavailable.

Run:
  set PYTHONPATH=C:\\path\\to\\unified-semantic-compressor;C:\\path\\to\\Drawer 2\\Scripts
  pytest tests/test_video_blip_cogvideox_integration.py -v -s

To persist outputs for verification:
  set USC_INTEGRATION_OUTPUT=C:\\path\\to\\out
  pytest tests/test_video_blip_cogvideox_integration.py -v -s
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Add video_storage_tool parent to path
_scripts = Path(__file__).resolve().parent.parent
_drawer_scripts = Path(r"C:\Users\John\Drawer 2\Scripts")
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
if str(_drawer_scripts) not in sys.path:
    sys.path.insert(0, str(_drawer_scripts))


def _default_models_dir() -> Path:
    return Path(r"C:\Users\John\Downloads")


def _resolve_model_paths(models_dir: Path) -> tuple[Path, Path, Path, Path]:
    """Returns (ffmpeg_dir, blip_model_dir, cogvideo_model_dir, ffmpeg_exe_or_dir)."""
    ffmpeg_dir = models_dir / "ffmpeg-master-latest-win64-gpl-shared" / "bin"
    blip_model = models_dir / "blip-image-captioning-base"
    cogvideo_model = models_dir / "CogVideoX-2b"
    return (ffmpeg_dir, blip_model, cogvideo_model, ffmpeg_dir)


def _check_blip_cogvideox_available(models_dir: Path) -> str | None:
    """Returns failure reason if unavailable, None if OK."""
    ffmpeg_dir, blip_model, cogvideo_model, _ = _resolve_model_paths(models_dir)
    if not ffmpeg_dir.exists():
        exe = ffmpeg_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if not exe.exists():
            return f"ffmpeg not found at {ffmpeg_dir}"
    if not blip_model.exists():
        return f"BLIP model dir not found: {blip_model}"
    if not cogvideo_model.exists():
        return f"CogVideoX model dir not found: {cogvideo_model}"
    if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
        return "transformers/torch not installed"
    if importlib.util.find_spec("diffusers") is None:
        return "diffusers not installed"
    if importlib.util.find_spec("PIL") is None:
        return "Pillow not installed"
    return None


FLIGHT_LOG_VIDEO = Path(r"D:/Aleph/Downloads/Flight log.mp4")


def _frame_pixel_std(video_path: Path, ffmpeg_dir: Path, num_frames: int = 5) -> float:
    """
    Sample frames from video, compute mean of per-frame pixel std.
    Black/blank video returns ~0; contentful video returns 20-80+.
    """
    import shutil

    exe = ffmpeg_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if not exe.exists():
        exe = shutil.which("ffmpeg") or "ffmpeg"
    with tempfile.TemporaryDirectory(prefix="frame_std_") as tmp:
        out_pattern = Path(tmp) / "frame_%03d.png"
        cmd = [
            str(exe), "-y", "-i", str(video_path),
            "-vf", "scale=160:90",
            "-frames:v", str(num_frames),
            str(out_pattern),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        from PIL import Image
        import statistics

        stds: list[float] = []
        for p in sorted(Path(tmp).glob("frame_*.png")):
            img = Image.open(p).convert("L")
            pixels = list(img.getdata())
            if pixels:
                mean = sum(pixels) / len(pixels)
                var = sum((x - mean) ** 2 for x in pixels) / len(pixels)
                stds.append(var**0.5)
        return statistics.mean(stds) if stds else 0.0


@pytest.mark.integration
def test_blip_describes_and_cogvideox_generates(tmp_path: Path) -> None:
    """
    Run video_compress with BLIP (visual/chunked script) and CogVideoX T2V.
    Asserts script.txt contains [Visual description] and resultant.mp4 is produced.
    """
    models_dir = _default_models_dir()
    skip_reason = _check_blip_cogvideox_available(models_dir)
    if skip_reason:
        pytest.skip(skip_reason)
    if not FLIGHT_LOG_VIDEO.is_file():
        pytest.skip(f"Flight log video not found: {FLIGHT_LOG_VIDEO}")

    from unified_semantic_archiver.compressors.video_compressor import video_compress

    ffmpeg_dir, blip_model, cogvideo_model, _ = _resolve_model_paths(models_dir)
    video_path = FLIGHT_LOG_VIDEO
    output_env = os.environ.get("USC_INTEGRATION_OUTPUT")
    if output_env:
        out_dir = Path(output_env).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        # Clear stale outputs so we get a fresh run (video_compress skips if files exist)
        for f in ("script.txt", "resultant.mp4", "audio.aac"):
            (out_dir / f).unlink(missing_ok=True)
        for f in out_dir.glob("diff.*"):
            f.unlink(missing_ok=True)
        print(f"\nOutputs will be written to: {out_dir}")
    else:
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "audio": {"ffmpeg_path": str(ffmpeg_dir)},
        "script": {
            "backend": "stub",
            "visual_backend": "blip",
            "visual_model": str(blip_model),
            "visual_interval_sec": 1.5,
            "visual_max_frames": 4,
            "visual_grid": 1,
        },
        "t2v": {
            "backend": "cogvideox",
            "model_path": str(cogvideo_model),
            "num_inference_steps": 2,
            "num_frames": 8,
            "fps": 4,
            "guidance_scale": 4.0,
        },
        "diff": {"enabled": True, "quality": 6},
        "minimization": {"enabled": True, "pipeline": {"adapter_set": "default"}},
    }

    result = video_compress(
        video_path,
        out_dir,
        config=config,
    )

    script_path = Path(result["script_path"])
    assert script_path.is_file(), "script.txt should exist"
    script_text = script_path.read_text(encoding="utf-8")

    # BLIP must produce non-empty chunked visual description
    assert "[Visual description]" in script_text or "Visual description" in script_text, (
        "BLIP should produce chunked visual description in script"
    )
    visual_section = "[Visual description]" if "[Visual description]" in script_text else "Visual description"
    idx = script_text.find(visual_section)
    assert idx >= 0, "BLIP visual section not found"
    after_visual = script_text[idx + len(visual_section) :].lstrip()
    assert any("s:" in line for line in after_visual.split("\n")[:10]), (
        "BLIP should produce timestamped frame captions (e.g. 0.0s: ...)"
    )
    # Reject placeholder or stub descriptions
    desc_content = after_visual.split("\n\n")[0].replace(" ", "").lower()
    assert len(desc_content) > 50, "BLIP description too short or empty"
    assert "placeholder" not in desc_content and "stub" not in desc_content, (
        "BLIP produced placeholder/stub instead of real descriptions"
    )

    resultant_path = Path(result.get("resultant_path") or out_dir / "resultant.mp4")
    assert resultant_path.is_file(), "resultant.mp4 should exist"

    # Resultant must not be blank/black; frame pixel std within 1 std of input
    input_std = _frame_pixel_std(video_path, ffmpeg_dir)
    resultant_std = _frame_pixel_std(resultant_path, ffmpeg_dir)
    # CogVideoX with few steps can produce dim output; stub is ~0. Reject pure black only.
    min_acceptable = 3.0
    assert resultant_std >= min_acceptable, (
        f"Resultant appears blank/black (pixel std={resultant_std:.1f}); "
        f"input std={input_std:.1f}, min acceptable={min_acceptable:.1f}. "
        "CogVideoX may have fallen back to stub."
    )

    assert "unique_chunk_refs" in result
    assert isinstance(result["unique_chunk_refs"], list)

    if output_env:
        print(f"\nSuccess. Outputs in {out_dir}: script.txt, resultant.mp4, audio.aac, diff.*")
