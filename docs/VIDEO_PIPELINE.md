# Full video pipeline and video_storage_tool

The **video compressor** in USC (`unified_semantic_archiver.compressors.video_compressor`) can run in two modes:

- **Stub:** When `video_storage_tool` is not available, the compressor uses a stub (no real describe/diff). USC works without it.
- **Full pipeline:** When `video_storage_tool` is available, the compressor uses it for: extract audio, describe (Whisper + visual via `video_to_script`), diff, script-to-video, and stores results in the continuum DB.

## Where video_storage_tool lives

Currently **video_storage_tool** is not part of USC. It lives in:

- **Drawer 2 (system-drawer):** `Scripts/video_storage_tool/` (e.g. `video_to_script.py`, `diff`, `script_to_video`, `audio`).

To run the full video pipeline from USC you must either:

1. Add the path to that package to `PYTHONPATH` (e.g. the Drawer 2 `Scripts` directory), or  
2. Install or link `video_storage_tool` so it is importable (e.g. copy the module into your env or a sibling package).

USC does not list `video_storage_tool` as a dependency; the video compressor catches `ImportError` and falls back to the stub. If you need the full pipeline, ensure `video_storage_tool` is on your Python path or will be distributed as a separate package in the future.
