# Partial Least Squares for Chunked-Image Style Descriptions

## Objective

Evaluate whether Partial Least Squares (PLS) can improve style-description feature quality for chunked images used in video minimization and generation composition. The goal is to stabilize style-aware scoring while preserving factual alignment and throughput.

## Hypotheses

1. A low-dimensional PLS latent space can denoise sparse/highly correlated visual-text style features better than direct linear weights.
2. PLS latent components improve ranking stability of selected chunks under small prompt/style perturbations.
3. PLS improves style adherence without materially degrading factual alignment.

## Candidate Inputs

- Chunk-level visual descriptors:
  - color moments, edge density, texture entropy, saliency coverage
  - motion-adjacent carryover stats from neighboring chunks (for temporal coherence)
- Text/style descriptors:
  - tokenized style description embeddings/projections
  - lexical style indicators (adjective density, metaphor density proxy, syntactic complexity proxy)
- Existing minimization features:
  - `token_density`, `token_entropy`, `diff_size_norm`, `bucket_depth_norm`
  - `style_description_density`, `style_alignment_ratio`

## PLS Formulation

- `X`: chunk feature matrix (visual + textual + existing minimization features)
- `Y`: supervision targets (style adherence score, factual alignment score, downstream acceptance label)
- Fit PLS with `n_components in [2..16]`.
- Use latent components in one of two ways:
  - Direct scoring model input replacement (`X_latent`)
  - Hybrid input (`X_raw_subset + X_latent`)

## Experiment Matrix

- Data slices:
  - short clips, long clips
  - low-motion, high-motion
  - sparse transcript, dense transcript
- Style prompts:
  - neutral, descriptive, baroque
  - style perturbations (synonymized and reordered forms)
- Model variants:
  - baseline logistic (current)
  - logistic + style features (current enhancement)
  - logistic + PLS latent
  - GLM tuned + PLS latent

## Metrics

- Style adherence:
  - style classifier agreement
  - style token recall against requested style lexicon
- Factual alignment:
  - entity/event consistency against extracted script and frame annotations
- Ranking stability:
  - Jaccard overlap of top-K selected chunks across style paraphrases
- Runtime:
  - added extraction/scoring latency
  - memory overhead per job

## Go/No-Go Criteria

Go if all are met:

1. +5% or better ranking stability (top-K overlap) versus non-PLS style-aware baseline.
2. No more than 2% factual alignment degradation.
3. Added end-to-end minimization latency <= 10%.
4. No regression in fallback behavior when PLS artifacts are missing.

No-Go if any criterion fails in at least two major data slices.

## Implementation Notes for a Future Pass

- Keep PLS behind config gate (`minimization.model.pls.enabled`).
- Persist fitted PLS artifact with clear feature-order metadata and schema version.
- Add hard fallback to current non-PLS logistic/GLM path when artifact validation fails.
- Track diagnostics in `minimization_report.json`:
  - `pls.enabled`, `pls.components`, `pls.artifact_version`, `pls.fallback_triggered`.
