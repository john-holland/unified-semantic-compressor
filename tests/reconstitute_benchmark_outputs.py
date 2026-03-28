"""
Reconstitute every successful benchmark cell output.

Usage:
  set PYTHONPATH=C:\\path\\to\\unified-semantic-compressor;C:\\path\\to\\Drawer 2\\Scripts
  python tests/reconstitute_benchmark_outputs.py --report D:/Aleph/Downloads/v2_cohort_report.json

Writes reconstituted.mp4 (resultant+audio) and reconstituted_original.mp4 (resultant+diff+audio)
into each successful cell's out_dir.

Note: If the benchmark ran without --results-root, out_dirs are in temp and may be gone.
Run the benchmark with --results-root to persist outputs, then run this script.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


def _safe_cell_name(key: str) -> str:
    """Sanitize matrix key for use in log/filename."""
    return key.replace("|", "_").replace("=", "-")


def _resolve_ffmpeg_exe(ffmpeg_path: Path | None) -> str:
    if ffmpeg_path is None:
        return "ffmpeg"
    if ffmpeg_path.is_file():
        return str(ffmpeg_path)
    if ffmpeg_path.is_dir():
        return str(ffmpeg_path / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"))
    return str(ffmpeg_path)


def _resolve_ffprobe_exe(ffmpeg_path: Path | None) -> str:
    if ffmpeg_path is None:
        return "ffprobe"
    if ffmpeg_path.is_file():
        return str(ffmpeg_path.with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe"))
    if ffmpeg_path.is_dir():
        return str(ffmpeg_path / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe"))
    return "ffprobe"


def _frame_pixel_std(video_path: Path, ffmpeg_path: Path | None, num_frames: int = 5) -> float:
    ffmpeg_exe = _resolve_ffmpeg_exe(ffmpeg_path)
    with tempfile.TemporaryDirectory(prefix="recon_verify_") as tmp:
        out_pattern = Path(tmp) / "frame_%03d.png"
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "scale=160:90",
            "-frames:v",
            str(num_frames),
            str(out_pattern),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        try:
            from PIL import Image
        except Exception:
            return 0.0
        stds: list[float] = []
        for p in sorted(Path(tmp).glob("frame_*.png")):
            img = Image.open(p).convert("L")
            pixels = list(img.getdata())
            if not pixels:
                continue
            mean = sum(pixels) / len(pixels)
            var = sum((x - mean) ** 2 for x in pixels) / len(pixels)
            stds.append(var ** 0.5)
        return statistics.mean(stds) if stds else 0.0


def _probe_video_stream_info(path: Path, ffmpeg_path: Path | None) -> dict:
    ffprobe_exe = _resolve_ffprobe_exe(ffmpeg_path)
    try:
        proc = subprocess.run(
            [
                ffprobe_exe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        parsed = json.loads(proc.stdout or "{}")
        streams = parsed.get("streams") or [{}]
        stream = streams[0] if streams else {}
        rate = str(stream.get("r_frame_rate") or "0/1")
        fps = 0.0
        if "/" in rate:
            n, d = rate.split("/", 1)
            try:
                fps = float(n) / max(float(d), 1.0)
            except Exception:
                fps = 0.0
        return {
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "fps": float(fps),
            "duration": float((parsed.get("format") or {}).get("duration") or 0.0),
        }
    except Exception:
        return {"codec": None, "width": 0, "height": 0, "fps": 0.0, "duration": 0.0}


def _edge_black_distance(video_path: Path, ffmpeg_path: Path | None, *, num_frames: int = 3, stripe: int = 4) -> float:
    ffmpeg_exe = _resolve_ffmpeg_exe(ffmpeg_path)
    with tempfile.TemporaryDirectory(prefix="recon_edge_") as tmp:
        out_pattern = Path(tmp) / "frame_%03d.png"
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "scale=160:90",
            "-frames:v",
            str(num_frames),
            str(out_pattern),
        ]
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        try:
            from PIL import Image
        except Exception:
            return 0.0
        distances: list[float] = []
        for p in sorted(Path(tmp).glob("frame_*.png")):
            img = Image.open(p).convert("RGB")
            w, h = img.size
            if w <= 2 * stripe or h <= 2 * stripe:
                continue
            samples: list[tuple[int, int, int]] = []
            for y in range(stripe):
                for x in range(w):
                    samples.append(img.getpixel((x, y)))
                    samples.append(img.getpixel((x, h - 1 - y)))
            for x in range(stripe):
                for y in range(stripe, h - stripe):
                    samples.append(img.getpixel((x, y)))
                    samples.append(img.getpixel((w - 1 - x, y)))
            if not samples:
                continue
            mean_r = sum(px[0] for px in samples) / len(samples)
            mean_g = sum(px[1] for px in samples) / len(samples)
            mean_b = sum(px[2] for px in samples) / len(samples)
            distances.append(math.sqrt(mean_r * mean_r + mean_g * mean_g + mean_b * mean_b))
        return statistics.mean(distances) if distances else 0.0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Reconstitute every successful benchmark cell output (resultant+audio, optional resultant+diff+audio)."
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path(r"D:/Aleph/Downloads/v2_cohort_report.json"),
        help="Path to v2_cohort_report.json",
    )
    p.add_argument(
        "--original-only",
        action="store_true",
        help="Only write reconstituted_original.mp4 (resultant+diff+audio); skip plain reconstituted.mp4",
    )
    p.add_argument(
        "--resultant-only",
        action="store_true",
        help="Only write reconstituted.mp4 (resultant+audio); skip reconstituted_original.mp4",
    )
    p.add_argument(
        "--ffmpeg-path",
        type=Path,
        default=None,
        help="Path to ffmpeg bin dir (e.g. C:/Users/John/Downloads/ffmpeg-master-latest-win64-gpl-shared/bin)",
    )
    p.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Write reconstituted files to output_root/<cell_name>/ instead of each cell's out_dir",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="Verify reconstituted outputs are non-empty and non-fog/black via frame std check",
    )
    p.add_argument(
        "--verify-min-std",
        type=float,
        default=5.0,
        help="Minimum frame std for verification (default 5.0)",
    )
    p.add_argument(
        "--verify-border-black",
        action="store_true",
        help="Optional: verify edge strips are near-black (useful for padded-border diagnostics).",
    )
    p.add_argument(
        "--verify-border-max-distance",
        type=float,
        default=30.0,
        help="Max mean RGB distance from black for edge-strip verification (default 30.0).",
    )
    p.add_argument(
        "--loop-strategy",
        choices=("loop", "hold"),
        default="loop",
        help="Loop strategy passed to reconstitute (default: loop).",
    )
    p.add_argument(
        "--trim-audio",
        action="store_true",
        help="Trim output duration to available video duration during reconstitution.",
    )
    args = p.parse_args()

    if not args.report.is_file():
        print(f"Error: report not found: {args.report}", file=sys.stderr)
        return 1

    report = json.loads(args.report.read_text(encoding="utf-8"))
    cells = report.get("matrix_cells", {})
    ffmpeg_path = args.ffmpeg_path
    if ffmpeg_path is None:
        try:
            from video_storage_tool import __main__ as cli
            cfg = cli._load_config(None)
            fp = (cfg.get("audio") or {}).get("ffmpeg_path")
            if fp:
                ffmpeg_path = Path(fp)
        except Exception:
            pass

    try:
        from video_storage_tool.reconstitute import reconstitute
    except ImportError as e:
        print(f"Error: video_storage_tool not on PYTHONPATH: {e}", file=sys.stderr)
        return 1

    reconstituted_count = 0
    skip_count = 0
    err_count = 0

    for key, payload in cells.items():
        if payload.get("execution_status") != "ok":
            continue
        out_dir = payload.get("out_dir")
        if not out_dir:
            skip_count += 1
            continue
        stored_dir = Path(out_dir)
        if not stored_dir.is_dir():
            print(f"Skipping {_safe_cell_name(key)}: out_dir not found: {stored_dir}", file=sys.stderr)
            skip_count += 1
            continue

        cell_ok = True
        dest_dir = (args.output_root / _safe_cell_name(key)) if args.output_root else stored_dir
        if args.output_root:
            dest_dir.mkdir(parents=True, exist_ok=True)
        if not args.original_only:
            out_mp4 = dest_dir / "reconstituted.mp4"
            try:
                reconstitute(
                    stored_dir,
                    out_mp4,
                    use_diff=False,
                    loop_strategy=args.loop_strategy,
                    trim_audio=args.trim_audio,
                    ffmpeg_path=str(ffmpeg_path) if ffmpeg_path else None,
                )
                print(f"  {_safe_cell_name(key)} -> {out_mp4.name}")
                if args.verify:
                    std = _frame_pixel_std(out_mp4, ffmpeg_path)
                    if out_mp4.stat().st_size <= 0 or std < args.verify_min_std:
                        print(
                            f"  {_safe_cell_name(key)} reconstituted.mp4 VERIFY FAILED: size={out_mp4.stat().st_size}, std={std:.2f}",
                            file=sys.stderr,
                        )
                        err_count += 1
                        cell_ok = False
                info_resultant = _probe_video_stream_info(stored_dir / "resultant.mp4", ffmpeg_path)
                info_out = _probe_video_stream_info(out_mp4, ffmpeg_path)
                print(
                    "    diag resultant: "
                    f"dur={info_resultant['duration']:.2f}s fps={info_resultant['fps']:.3f} "
                    f"geom={info_resultant['width']}x{info_resultant['height']}"
                )
                print(
                    "    diag reconstituted: "
                    f"dur={info_out['duration']:.2f}s fps={info_out['fps']:.3f} "
                    f"geom={info_out['width']}x{info_out['height']} loop={args.loop_strategy} trim_audio={args.trim_audio}"
                )
            except Exception as e:
                print(f"  {_safe_cell_name(key)} reconstituted.mp4 FAILED: {e}", file=sys.stderr)
                err_count += 1
                cell_ok = False

        if not args.resultant_only:
            out_orig = dest_dir / "reconstituted_original.mp4"
            diff_path = stored_dir / "diff.mkv"
            if not diff_path.exists():
                diff_path = stored_dir / "diff.ogv"
            if diff_path.exists():
                try:
                    reconstitute(
                        stored_dir,
                        out_orig,
                        use_diff=True,
                        loop_strategy=args.loop_strategy,
                        trim_audio=args.trim_audio,
                        ffmpeg_path=str(ffmpeg_path) if ffmpeg_path else None,
                    )
                    print(f"  {_safe_cell_name(key)} -> {out_orig.name}")
                    if args.verify:
                        std = _frame_pixel_std(out_orig, ffmpeg_path)
                        if out_orig.stat().st_size <= 0 or std < args.verify_min_std:
                            print(
                                f"  {_safe_cell_name(key)} reconstituted_original.mp4 VERIFY FAILED: size={out_orig.stat().st_size}, std={std:.2f}",
                                file=sys.stderr,
                            )
                            err_count += 1
                            cell_ok = False
                    info_diff = _probe_video_stream_info(diff_path, ffmpeg_path)
                    info_out_orig = _probe_video_stream_info(out_orig, ffmpeg_path)
                    print(
                        "    diag diff/output: "
                        f"diff_codec={info_diff['codec']} diff_dur={info_diff['duration']:.2f}s "
                        f"diff_fps={info_diff['fps']:.3f} diff_geom={info_diff['width']}x{info_diff['height']} "
                        f"out_dur={info_out_orig['duration']:.2f}s out_fps={info_out_orig['fps']:.3f} "
                        f"out_geom={info_out_orig['width']}x{info_out_orig['height']} "
                        f"loop={args.loop_strategy} trim_audio={args.trim_audio}"
                    )
                    if info_diff["width"] > 0 and info_diff["height"] > 0:
                        if (
                            info_out_orig["width"] != info_diff["width"]
                            or info_out_orig["height"] != info_diff["height"]
                        ):
                            print(
                                f"  {_safe_cell_name(key)} GEOMETRY MISMATCH: output {info_out_orig['width']}x{info_out_orig['height']} vs diff {info_diff['width']}x{info_diff['height']}",
                                file=sys.stderr,
                            )
                            err_count += 1
                            cell_ok = False
                    if info_diff["fps"] > 0 and info_out_orig["fps"] > 0:
                        if abs(info_out_orig["fps"] - info_diff["fps"]) > 0.1:
                            print(
                                f"  {_safe_cell_name(key)} FPS MISMATCH: output {info_out_orig['fps']:.3f} vs diff {info_diff['fps']:.3f}",
                                file=sys.stderr,
                            )
                            err_count += 1
                            cell_ok = False
                    if args.verify and args.verify_border_black:
                        edge_dist = _edge_black_distance(out_orig, ffmpeg_path)
                        if edge_dist > args.verify_border_max_distance:
                            print(
                                f"  {_safe_cell_name(key)} BORDER CHECK FAILED: edge_distance={edge_dist:.2f} > {args.verify_border_max_distance:.2f}",
                                file=sys.stderr,
                            )
                            err_count += 1
                            cell_ok = False
                except Exception as e:
                    print(f"  {_safe_cell_name(key)} reconstituted_original.mp4 FAILED: {e}", file=sys.stderr)
                    err_count += 1
                    cell_ok = False
            else:
                print(f"  {_safe_cell_name(key)}: no diff, skipping reconstituted_original.mp4", file=sys.stderr)

        if cell_ok:
            reconstituted_count += 1

    print(f"\nDone. Cells reconstituted: {reconstituted_count}, skipped: {skip_count}, errors: {err_count}")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
