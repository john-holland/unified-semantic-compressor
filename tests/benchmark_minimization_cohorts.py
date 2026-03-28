"""
Ad-hoc benchmark for minimization adapter cohorts.

Usage:
  python tests/benchmark_minimization_cohorts.py --input "d:/Aleph/Downloads/Flight log.mp4"
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from unified_semantic_archiver.compressors.video_compressor import video_compress


def run(input_path: Path) -> dict:
    configs = {
        "default": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"backend": "stub", "visual_backend": "none"},
            "t2v": {"backend": "stub"},
            "diff": {"enabled": True, "quality": 6},
            "minimization": {"enabled": True, "pipeline": {"adapter_set": "default"}},
        },
        "cairn_audio_v1": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"backend": "stub", "visual_backend": "none"},
            "t2v": {"backend": "stub"},
            "diff": {"enabled": True, "quality": 6},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "cairn_audio_v1"},
                "cairn": {"enabled": True, "max_depth": 3},
            },
        },
        "cairn_residual_v1": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"backend": "stub", "visual_backend": "none"},
            "t2v": {"backend": "stub"},
            "diff": {"enabled": True, "quality": 6},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "cairn_residual_v1"},
                "cairn": {"enabled": True, "max_depth": 3},
            },
        },
        "planar_hyperplane_v1": {
            "audio": {"format": "aac", "max_mb": 5.0},
            "script": {"backend": "stub", "visual_backend": "none"},
            "t2v": {"backend": "stub"},
            "diff": {"enabled": True, "quality": 6},
            "minimization": {
                "enabled": True,
                "pipeline": {"adapter_set": "planar_hyperplane_v1"},
                "cairn": {"enabled": True, "max_depth": 3},
                "hyperplane": {"intercept": -1.8},
            },
        },
    }

    report = {"input_path": str(input_path), "input_bytes": input_path.stat().st_size, "cohorts": {}}
    for name, cfg in configs.items():
        out_dir = Path(tempfile.mkdtemp(prefix=f"bench_{name}_"))
        result = video_compress(input_path, out_dir, config=cfg)
        files = {p.name: p.stat().st_size for p in out_dir.iterdir() if p.is_file()}
        report["cohorts"][name] = {
            "out_dir": str(out_dir),
            "stored_total_bytes": sum(files.values()),
            "unique_chunk_refs_count": len(result.get("unique_chunk_refs") or []),
            "files": files,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    data = run(args.input)
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
