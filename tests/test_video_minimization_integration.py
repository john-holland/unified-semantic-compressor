import json
import sys
import types
from pathlib import Path

from unified_semantic_archiver.compressors.video_compressor import video_compress
from unified_semantic_archiver.media import UscMediaService


def _install_fake_video_storage_tool(tmp_path: Path):
    pkg = types.ModuleType("video_storage_tool")
    main_mod = types.ModuleType("video_storage_tool.__main__")
    audio_mod = types.ModuleType("video_storage_tool.audio")
    diff_mod = types.ModuleType("video_storage_tool.diff")
    s2v_mod = types.ModuleType("video_storage_tool.script_to_video")
    v2s_mod = types.ModuleType("video_storage_tool.video_to_script")
    media_utils_mod = types.ModuleType("video_storage_tool.media_utils")
    recon_mod = types.ModuleType("video_storage_tool.reconstitute")
    cache_mod = types.ModuleType("video_storage_tool.stream_cache")

    def extract_and_compress_audio(_video_path, out_dir, **_kwargs):
        p = Path(out_dir) / "audio.aac"
        p.write_bytes(b"audio")
        return p

    def video_to_script(_video_path, _audio_path, out_dir, **_kwargs):
        p = Path(out_dir) / "script.txt"
        p.write_text("flight plane sky cloud mountain", encoding="utf-8")
        return p

    def script_to_video(_script_path, out_dir, **_kwargs):
        p = Path(out_dir) / "resultant.mp4"
        p.write_bytes(b"video")
        return p

    def compute_diff(_orig, _res, out_dir, **_kwargs):
        p = Path(out_dir) / "diff.ogv"
        p.write_bytes(b"diff")
        return p

    def run_store(_input_path, out_dir, **_kwargs):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "script.txt").write_text("flight plane sky cloud mountain", encoding="utf-8")
        (out / "resultant.mp4").write_bytes(b"video")
        (out / "diff.ogv").write_bytes(b"diff")
        (out / "manifest.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    class StreamCache:
        def __init__(self, *_args, **_kwargs):
            pass

        def get(self, *_args, **_kwargs):
            return None

        def put(self, _job_id, _use_original, source_path):
            return source_path

    main_mod.run_store = run_store
    audio_mod.extract_and_compress_audio = extract_and_compress_audio
    diff_mod.compute_diff = compute_diff
    s2v_mod.script_to_video = script_to_video
    v2s_mod.video_to_script = video_to_script
    media_utils_mod.is_image_input = lambda _path: False
    media_utils_mod.get_image_format = lambda _path: None
    recon_mod.reconstitute = lambda *_args, **_kwargs: None
    cache_mod.StreamCache = StreamCache

    sys.modules["video_storage_tool"] = pkg
    sys.modules["video_storage_tool.__main__"] = main_mod
    sys.modules["video_storage_tool.audio"] = audio_mod
    sys.modules["video_storage_tool.diff"] = diff_mod
    sys.modules["video_storage_tool.script_to_video"] = s2v_mod
    sys.modules["video_storage_tool.video_to_script"] = v2s_mod
    sys.modules["video_storage_tool.media_utils"] = media_utils_mod
    sys.modules["video_storage_tool.reconstitute"] = recon_mod
    sys.modules["video_storage_tool.stream_cache"] = cache_mod


def test_video_compress_minimization_enabled_returns_refs(tmp_path: Path):
    _install_fake_video_storage_tool(tmp_path)
    video = tmp_path / "input.mp4"
    video.write_bytes(b"in")
    result = video_compress(
        video,
        tmp_path / "out",
        config={"minimization": {"enabled": True, "threshold": 0.2}},
    )
    assert isinstance(result["unique_chunk_refs"], list)
    assert len(result["unique_chunk_refs"]) > 0


def test_media_service_attaches_minimization_metadata(tmp_path: Path):
    _install_fake_video_storage_tool(tmp_path)
    service = UscMediaService(
        storage_root=tmp_path / "storage",
        config_path=tmp_path / "missing.yaml",
        settings_path=tmp_path / "settings.json",
    )
    service.update_settings({"minimization": {"enabled": True, "threshold": 0.2}})

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"in")
    out_dir = tmp_path / "storage" / "tenant-a" / "job-a"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "input.mp4").write_bytes(b"in")

    service._run_store(
        input_path=input_path,
        out_dir=out_dir,
        job_id="job-a",
        tenant_id="tenant-a",
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "minimization" in manifest
    assert manifest["minimization"]["enabled"] is True
    assert len(manifest["minimization"]["unique_chunk_refs"]) > 0
