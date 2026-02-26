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
            except Exception as e:
                print(f"  {_safe_cell_name(key)} reconstituted.mp4 FAILED: {e}", file=sys.stderr)
                err_count += 1
                cell_ok = False

        if not args.resultant_only:
            out_orig = dest_dir / "reconstituted_original.mp4"
            diff_path = stored_dir / "diff.ogv"
            if not diff_path.exists():
                diff_path = stored_dir / "diff.mkv"
            if diff_path.exists():
                try:
                    reconstitute(
                        stored_dir,
                        out_orig,
                        use_diff=True,
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
