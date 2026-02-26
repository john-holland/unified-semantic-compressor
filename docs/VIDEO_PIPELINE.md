# Full video pipeline and video_storage_tool

The USC media layer now has two relevant surfaces:

- `unified_semantic_archiver.compressors.video_compressor` (compressor pipeline entrypoint).
- `unified_semantic_archiver.media.UscMediaService` (service-facing parity API used by Continuum).

The compressor can run in two modes:

- **Stub:** When `video_storage_tool` is not available, the compressor uses a stub (no real describe/diff). USC works without it.
- **Full pipeline:** When `video_storage_tool` is available, the compressor uses it for: extract audio, describe (Whisper + visual via `video_to_script`), diff, script-to-video, and stores results in the continuum DB.

## Minimization ETL adapter pipeline

USC now supports an ETL-style minimization path where each stage is swappable via adapters while keeping model artifacts portable:

1. extract artifacts
2. tokenize description text (thesaurus normalization)
3. quadtree bucketing per frame
4. logistic/hyperplane scoring
5. bucket selection
6. persistence

This runs in both:

- compressor path (`video_compressor`)
- runtime path (`UscMediaService`) used by Continuum `/api/media/*`

Enable with media settings:

```json
{
  "minimization": {
    "enabled": true,
    "threshold": 0.55,
    "max_refs": 128,
    "grid_size": 2,
    "pipeline": {
      "adapter_set": "default",
      "stages": {
        "extract": "default",
        "tokenize": "default",
        "bucket": "default",
        "score": "default",
        "select": "default",
        "persist": "default"
      }
    },
    "model": {
      "path_json": "",
      "path_joblib": "",
      "format_preference": "json_first",
      "glm": {
        "enabled": false,
        "family": "binomial",
        "link": "logit",
        "l1_alpha": 0.0,
        "l2_alpha": 0.0,
        "temperature": 1.0
      }
    },
    "quadtree": {
      "max_depth": 2
    },
    "cairn": {
      "enabled": true,
      "max_depth": 3
    },
    "codec": {
      "residual_enabled": true,
      "residual_schema": "cairn_residual_v1",
      "residual_deadzone_q": 2
    },
    "hyperplane": {
      "intercept": -1.8,
      "coefficients": {}
    },
    "experiments": {
      "enabled": true,
      "cohort_key": "hash",
      "cohorts": {
        "default": 40,
        "cairn_audio_v1": 25,
        "cairn_residual_v1": 20,
        "planar_hyperplane_v1": 15
      }
    }
  }
}
```

Style-description control:

```json
{
  "script": {
    "video_style_description": ""
  }
}
```

When provided, this text is propagated into minimization feature construction. It contributes to
`style_description_density` and `style_alignment_ratio` so scoring can favor buckets that better
align with the requested narrative style while remaining grounded to extracted script content.

Model loading order:

- default: JSON artifact first
- optional: sklearn/joblib artifact if configured
- fallback: self-evident built-in default weights

Adapter-set cohort options:

- `default`: baseline minimization adapters
- `cairn_audio_v1`: cairn-sidecar enhanced feature adapters
- `cairn_residual_v1`: packed residual cairn stream feature adapters
- `planar_hyperplane_v1`: planar division + hyperplane regression scorer
- `glm_tuned_v1`: default ETL adapters with GLM tuning enabled via `minimization.model.glm`

GLM tuning controls:

- `family`: `binomial | poisson | gaussian`
- `link`: `logit | probit | cloglog | log | identity`
- `l1_alpha`: coefficient soft-thresholding strength (default `0.0`)
- `l2_alpha`: coefficient shrinkage factor (default `0.0`)
- `temperature`: post-linear scaling on model margin (default `1.0`)

With `glm.enabled=false`, behavior remains compatible with the existing logistic scorer.

Benchmark harness for cohort comparisons:

```bash
python tests/benchmark_minimization_cohorts.py --input "d:/Aleph/Downloads/Flight log.mp4"
```

## V2 adapter optimization

V2 adds per-adapter requirement checks and deterministic fallback routing.

- Requirement contract keys per adapter:
  - `adapter_id`
  - `required_python_packages`
  - `required_binaries`
  - `required_model_artifacts`
  - `runtime_fallback_adapter`
- Runtime behavior:
  - evaluate requirements before pipeline assembly
  - if missing requirements, route to fallback adapter
  - persist requirement status in minimization diagnostics

V2 transcript and SFX policy:

- `transcript.policy`: `whisper_required | whisper_preferred | stub_allowed`
- `audio_captioning.enabled`
- `audio_captioning.mode`: `always | speech_gap_only | non_speech_only`

## Local model paths (Download folder)

Script ASR and audio captioning support loading models from local paths:

- **`script.model_path`** – Optional path to openai-whisper checkpoint. Can be a `.pt` file or a directory containing `{model}.pt` (e.g. `base.pt`). When set and the path exists, Whisper loads from it instead of the cache.
- **`audio_captioning.model_path`** – Optional path to a HuggingFace-format model directory for non-speech audio captioning. When set and the path exists, the pipeline loads from it instead of `model_id`.

Expected Download-folder layout for the V2 benchmark (`--models-dir`, default `C:\Users\John\Downloads`):

| Path | Purpose |
|------|---------|
| `ffmpeg-master-latest-win64-gpl-shared/bin` | ffmpeg |
| `blip-image-captioning-base/` | BLIP visual |
| `blip2-opt-2.7b/` | BLIP2 visual |
| `CogVideoX-2b/` | T2V |
| `whisper-base/` | openai-whisper checkpoint (contains `base.pt` or is a single `.pt` file) |
| `openai-whisper-base/` | HuggingFace-format model for audio captioning (e.g. from `huggingface-cli download openai/whisper-base`) |

V2 storage trim controls:

- `minimization.cairn.write_debug_json` (default false)
- `minimization.cairn.emit_resultant_audio` (default false)
- residual sidecar remains primary cairn artifact (`audio.cairn.residual.bin`)

V2 benchmark command:

```bash
python tests/benchmark_v2_cohorts.py --input "d:/Aleph/Downloads/Flight log.mp4" --out "d:/Aleph/Downloads/v2_cohort_report.json" --visual-grid 2 --blip2-model-id "Salesforce/blip2-opt-2.7b"
```

Notes:

- `--visual-grid` controls exhaustive region captions: `1` whole frame, `2`=2x2, `3`=3x3.
- `--blip2-model-id` provides a Hub fallback when local BLIP2 weights are missing/incomplete.

V2 benchmark output schema (JSON 2.0 style):

- Top-level:
  - `schema_version` (`"2.0"`)
  - `matrix_dimensions` and `matrix_cardinality`
  - `matrix_stats` (`success_count`, `failure_count`)
  - `matrix_rollups` (runtime/cost grouped by script backend, t2v backend, visual backend, lossless)
  - `adapter_config_matrix` (configured script/t2v/minimization adapter portfolio)
  - `portfolio.runtime` (start/end/total duration + per-cohort durations)
  - `comparisons[]` (cohort to closest-stub relation entries)
- Per matrix cell (`matrix_cells.<matrix_key>`):
  - `execution_status` (`ok|failed`)
  - `failure_reason` (strict-fail reason for unavailable backends/models/deps)
  - `runtime.runtime_duration_sec`
  - `runtime.estimated_compute_cost_units`
  - `links.closest_stub_cohort`
  - `links.closest_stub_result_path`
  - `links.closest_stub_report_path`

The benchmark uses strict-fail matrix behavior for unavailable backend/model/dependency cells and writes a markdown sidecar report next to the JSON output (`.md`) summarizing matrix status, runtime/cost rollups, and closest-stub links.

### Where test reports end up

| Report type | Location |
|-------------|----------|
| **Benchmark JSON** | `--out` path (default `d:\Aleph\Downloads\v2_cohort_report.json`) |
| **Benchmark markdown** | Same path with `.md` (e.g. `v2_cohort_report.md`) |
| **Cell outputs** | `--results-root/cell_XXX_hash/` when `--results-root` is set; otherwise temp dirs |
| **pytest** | stdout (terminal). For XML: `pytest --junitxml=report.xml`; for HTML: `pytest --html=report.html` |

Current visual matrix options:

- `script.visual_backend`: `blip`, `blip2`
- `script.visual_grid`: `1`, `2`, `3`

Diff/reconstitution verification:

```bash
python tests/reconstitute_benchmark_outputs.py --report "d:/Aleph/Downloads/v2_cohort_report.json" --verify --verify-min-std 5.0
```

This checks reconstituted outputs are non-empty and rejects fog/black-ish videos using frame pixel std.

## Where video_storage_tool lives

Currently **video_storage_tool** is not part of USC. It lives in:

- **Drawer 2 (system-drawer):** `Scripts/video_storage_tool/` (e.g. `video_to_script.py`, `diff`, `script_to_video`, `audio`).

To run the full video pipeline from USC you must either:

1. Add the path to that package to `PYTHONPATH` (e.g. the Drawer 2 `Scripts` directory), or  
2. Install or link `video_storage_tool` so it is importable (e.g. copy the module into your env or a sibling package).

USC does not list `video_storage_tool` as a dependency; the pipeline catches `ImportError` and can fall back to a stub surface. For full media parity behavior, ensure `video_storage_tool` is on your Python path.
