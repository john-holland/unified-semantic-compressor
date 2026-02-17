# Unified Semantic Archiver: Theory, Current State, and Roadmap

This document describes the theory behind the archiver, where the implementation stands today, an assessment of the flowering generative compressor ring, and concrete suggestions and follow-ups.

---

## 1. Theory

### 1.1 Semantic compression loop

The archiver is built on a single pipeline that repeats across media types:

1. **Describe** — Turn raw media into a semantic representation (script, transcript, schema, exemplars). For video: Whisper + visual description → script. For data: schema + statistics + exemplars.
2. **Generate proximal** — From that description, produce a “proximal” artifact that approximates the original (e.g. script → resultant video via T2V, or schema → sample dataset).
3. **Diff** — Compare original and proximal to get a residual (visual diff, edit distance, or statistical gap).
4. **Minimize** — Use the residual to identify unique compression: high-residual regions become candidates for “unique chunks” or **unique kernels**. The goal is to iteratively refine the descriptor or the generator so the residual shrinks, while explicitly tracking what does not shrink.
5. **Store** — Persist descriptors, diff blobs, and kernel metadata in the **continuum DB** so the system has one durable record of what was compressed, how, and what remains hard.

So compression here is **lossy semantic compression**: we keep a description and a residual, not bit-for-bit fidelity. The “loss” is structured: it is the diff and the set of unique kernels that feed back into research and model improvement.

### 1.2 The ring: Video → Audio → Library → Data → Video

The **flowering ring** is the idea that compressors are not isolated; they form a ring and can delegate to neighbors:

- **Video** can pull in **audio** (extract soundtrack, describe it, reattach or reference it).
- **Audio** might later reference **library** (e.g. sheet music, metadata) or **data** (transcript alignments).
- **Library** (code, docs, assets) can reference **data** (configs, schemas) and eventually feed **video** (e.g. UI flows, demos).
- **Data** is the catch-all for structured/semi-structured content and is the natural home for **unique kernels**: chunks that other compressors have tried and failed to shrink further. The data compressor’s special role is to take those kernels and try again (schema inference, exemplar extraction, aggregation), or to flag them for research.

So the ring is both a **dispatch** (by media type) and a **dependency graph** (each compressor can call others). “Flowering” suggests that the ring can grow (new compressors, new links) and that high-value content (kernels) can “bloom” into research and improvement.

### 1.3 Unique kernels and the research feed

**Unique kernels** are semantic chunks that remain incompressible after one or more attempts: high residual, or explicitly flagged. They are stored in `unique_kernels` with a status: `pending`, `compressed`, or `flagged_research`. The idea:

- **pending** — Not yet retried by the data compressor (or another pass).
- **compressed** — A later pass managed to reduce them (or they were merged into a better chunk).
- **flagged_research** — Still incompressible; feed to humans or to an improvement pipeline (e.g. Cursor, model fine-tuning, prompt engineering).

The **research feed** (e.g. `build_improvement_context`, Cursor call service) packages these kernels plus recent compression runs and chunk metadata into a context that can drive:

- Algorithm changes (e.g. different chunking, different description model).
- Model updates (e.g. fine-tune the T2V or the descriptor on residuals).
- Prompt or schema tweaks.

So the continuum is not only an archive; it is the **memory** for a feedback loop: compress → detect kernels → research → improve compressors → compress again.

### 1.4 Continuum DB as single source of truth

The continuum DB holds:

- **semantic_chunks** — What was compressed (media type, chunk_key, description_text, diff_blob_ref, parent_id for hierarchy).
- **unique_kernels** — Which chunks resist compression (chunk_id, source_compressor, residual_metric, attempt_count, status).
- **compression_runs** — History of runs (media_id, strategy, config_json, output_hash).
- **research_suggestions** — Output of the research step (source, recommendation_text, context_json, status).
- **continuum_meta** — Key-value metadata for schema versioning and config.
- **spatial_4d**, **document_blobs** — For future use (volumes, blob refs).

Everything that the ring produces and consumes is intended to flow through this schema, so that the Unity Explorer, the ETL, and any future services share one view of “what exists” and “what’s next.”

---

## 2. Where we are

### 2.1 Implemented

- **Ring orchestrator** — Dispatches by `media_type` (video, image, audio, library, data); exposes `run_ring()` and `run_unique_kernel_pass()`.
- **Video compressor** — Full pipeline when `video_storage_tool` is available: extract audio → describe (video-to-script) → generate (script-to-video) → diff → minimize (stub) → store in continuum. Falls back to stub otherwise.
- **Image** — Treated as single-frame video; reuses video pipeline.
- **Audio / Library / Data compressors** — Stubs or partial: describe (e.g. data: schema + exemplar stub), store in DB; no full generate/diff/minimize yet.
- **Data compressor** — `compress_unique_kernels()`: reads `unique_kernels` (pending), updates status to `compressed` or `flagged_research` (stub logic: attempt_count >= 2 → flagged).
- **Continuum DB** — Schema, ContinuumDb micro-ORM, init, and read/write for all main tables.
- **ETL** — Luigi pipeline (Extract → Transform → Load) as identity stub; writes to continuum_meta and can be extended.
- **Research** — `improvement_feed.build_improvement_context()`, `unique_kernel_store`, Cursor call service that writes context JSON and documents manual Cursor workflow.
- **CLI** — init, run-etl, compress, cursor-research; `query_db` for Unity Explorer.
- **Unity** — Continuum Explorer window: DB path, table list, read-only SQL.

### 2.2 Gaps

- **Minimize** — Video’s “minimize toward unique chunks” is a stub (`_minimize_stub` returns []); no real residual-based chunk selection or kernel recording from video yet.
- **Residual metrics** — No consistent definition or computation of “residual” across compressors; `unique_kernels.residual_metric` is set in data compressor but not yet from video/audio/library.
- **Audio / Library** — No full describe → generate → diff → minimize; no delegation from video to audio beyond “extract and compress audio” (file-level, not ring-level semantic handoff).
- **Ring delegation** — Orchestrator delegates by type but compressors do not yet call each other (e.g. video does not “ask” the audio compressor to describe the soundtrack as a first-class chunk).
- **ETL** — Does not yet drive the ring (e.g. “on new file in input/, run_ring(media_path, type)”); it only lists files and loads metadata.
- **Cursor** — Context is written to JSON; no automated Cursor invocation; suggestions are not yet read back into the DB from Cursor output (only manual persist).

---

## 3. The flowering generative compressor ring: assessment and direction

### 3.1 Strengths of the design

- **Single pipeline** — Describe → generate → diff → minimize is a clear, repeatable pattern. It fits video (script + T2V + diff) and can be adapted for audio, library, and data.
- **Unique kernels** — Giving a name and a table to “what we couldn’t compress” turns failure into data. That directly supports a research loop and avoids the ring being a one-way sink.
- **Data compressor as kernel consumer** — Making the data compressor the one that repeatedly attacks pending kernels is a good separation of concerns: other compressors produce kernels; data (and research) consume them.
- **Continuum as hub** — One DB for chunks, kernels, runs, and suggestions keeps the system coherent and queryable (Unity, CLI, future tools).

### 3.2 Making the ring more “flowering”

- **Explicit delegation** — Let video compressor call `audio_compress()` on the extracted track and attach that result as a child chunk or a reference. Same for library (e.g. “this video references this doc”) and data (“this chunk’s schema”). That turns the ring into a real graph of dependencies, not just four separate entry points.
- **Bidirectional links** — When data compressor compresses a kernel that came from video, it could write back a link (e.g. `semantic_chunks.parent_id` or a new `derived_from` table) so the tree is visible: “this data chunk was derived from this video chunk.”
- **Configurable ring order** — Right now the “ring” is implicit (video → audio → library → data). Making order and “who can call whom” configurable (e.g. a small config or table) would allow adding new compressors or skipping steps without code churn.
- **Generative everywhere** — Today only video has a real “generate proximal” (T2V). Audio could have “transcript → TTS or reconstruction,” library “code → run or doc summary,” data “schema → sample rows.” Even stubs (e.g. “identity” or “exemplar-only”) would complete the loop and produce diffs and residuals.

### 3.3 Suggestions for the ring

1. **Define residual formally** — One formula or protocol per media type (e.g. video: mean squared error of diff frames, or length of edit script; data: schema distance + exemplar coverage). Store it in `unique_kernels.residual_metric` from every compressor so the data compressor and research feed can rank and filter.
2. **Implement minimize in video** — From the diff or the script, identify segments or frames with highest residual; create child chunks or kernel records with `source_compressor='video'` and a residual_metric so the data compressor and research see them.
3. **One “ring round” primitive** — A single command or API that: run ETL (or watch) → for each new or updated asset, run_ring(media_path, inferred_type) → then run_unique_kernel_pass(). That closes the loop from “new input” to “kernels ready for research.”
4. **Cursor ↔ DB** — When Cursor (or a script) produces a suggestion, persist it with `persist_suggestion()`; optionally have a small “suggestions” view in Unity or CLI so the improvement feed is visible and actionable.

---

## 4. Follow-ups and priorities

### 4.1 High impact

- **Video minimize** — Replace `_minimize_stub` with logic that, from the diff or script, creates semantic_chunks and/or unique_kernel rows for high-residual regions; optionally call `record_kernel()` from video_compressor when a segment is marked incompressible.
- **Residual metric** — Add a function per compressor that returns a scalar residual (or “N/A”); call it at the end of each compress and pass it into `unique_kernel_insert` / update.
- **ETL → ring** — In LoadTask (or a new task), for each extracted file, infer media_type and call `run_ring(media_path, media_type, out_dir, db_path=...)` so that “drop files in input/” automatically runs the full pipeline.

### 4.2 Medium impact

- **Audio compressor** — Full pipeline: describe (transcript + maybe structure) → generate (TTS or reconstruction) → diff (e.g. waveform or transcript edit) → minimize → store; optionally allow video to pass an audio path and get back a chunk_id or descriptor.
- **Library compressor** — Describe (e.g. AST, doc outline, asset list) → generate (e.g. summary or stub code) → diff → minimize → store; link from video or data when relevant.
- **Cursor integration** — Document or script: “after cursor-research, run this to persist suggestions from Cursor output”; or a small listener that watches a file and calls `persist_suggestion()`.

### 4.3 Nice to have

- **Spatial 4D / document_blobs** — Use these tables when you have volumetric or blob references (e.g. diff blobs by volume, or large binaries by hash).
- **Config per run** — Store full `config` in compression_runs.config_json so you can reproduce or vary runs (e.g. different T2V backends, grid sizes).
- **Improvement feed UI** — In Unity or a small web view: list unique_kernels (flagged_research), recent runs, and research_suggestions so the loop is visible without querying the DB by hand.

---

## 5. Summary

The Unified Semantic Archiver is built on a clear **semantic compression loop** (describe → generate → diff → minimize → store) and a **ring of compressors** (video, audio, library, data) with a shared **continuum DB** and a **research feed** driven by **unique kernels**. The theory is sound; the current implementation has the structure in place (orchestrator, video pipeline, DB, ETL stub, research, Cursor context) with most of the “generative” and “minimize” steps still stubbed or partial. The highest-leverage next steps are: implement video’s minimize and residual, define and store residual metrics everywhere, and connect ETL to the ring so that new inputs automatically flow through the ring and into the kernel/research pipeline. Making the ring more “flowering” means explicit delegation between compressors, bidirectional links from data back to source chunks, and completing the generative and minimize steps for audio and library so the whole ring is a closed, improving system.
