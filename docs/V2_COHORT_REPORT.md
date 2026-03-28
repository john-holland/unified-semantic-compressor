# V2 Matrix Portfolio Report

Source JSON: `d:\Aleph\Downloads\v2_cohort_report.json`

Input clip: `d:\Aleph\Downloads\Flight log.mp4`
Input bytes: `18,473,453`

## Matrix summary

- Matrix cardinality: `64`
- Success cells: `64`
- Failed cells: `0`
- Added visual dimension: `script.visual_backend` = `blip`, `blip2`

## Runtime/cost rollups

- `by_script_backend`: `{"stub": {"avg_runtime_sec": 15.074873059371384, "count": 32.0, "sum_cost_units": 3002.6505615995266}, "whisper": {"avg_runtime_sec": 15.5265794906245, "count": 32.0, "sum_cost_units": 9688.440291598672}}`
- `by_t2v_backend`: `{"cogvideox": {"avg_runtime_sec": 14.922966412497772, "count": 32.0, "sum_cost_units": 11692.519946398214}, "stub": {"avg_runtime_sec": 15.678486137498112, "count": 32.0, "sum_cost_units": 998.5709067999851}}`
- `by_visual_backend`: `{"blip": {"avg_runtime_sec": 15.557850274994053, "count": 32.0, "sum_cost_units": 6333.398591497622}, "blip2": {"avg_runtime_sec": 15.043602275001831, "count": 32.0, "sum_cost_units": 6357.692261700577}}`
- `by_lossless`: `{"False": {"avg_runtime_sec": 15.649155156250345, "count": 32.0, "sum_cost_units": 6363.051006098918}, "True": {"avg_runtime_sec": 14.952297393745539, "count": 32.0, "sum_cost_units": 6328.03984709928}}`

## JSON 2.0 links

- Per matrix cell: `matrix_cells.<matrix_key>.links.closest_stub_cohort`, `closest_stub_result_path`, `closest_stub_report_path`
- Top-level: `comparisons[]` relation objects for cohort -> closest stub

## Portfolio runtime

- `portfolio.runtime.total_duration_sec` reports end-to-end matrix runtime.
- `portfolio.runtime.per_cell_duration_sec` reports run duration per matrix cell.
