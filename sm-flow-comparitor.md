# Comparison Flows — Complete Step-by-Step Breakdown

There are two ways to initiate a comparison experiment, both of which use the document pipeline Express state machine and the comparison Standard state machine:

- **Flow A — gold.html (browser-initiated):** User picks a document and reference file in the browser, chooses N runs, and clicks Run Test. The browser uploads the document once, calls `POST /experiments`, then polls `GET /experiments/{experimentId}` every 10s until the comparison state machine completes.
- **Flow B — direct API call:** Caller POSTs to `POST /experiments` directly with an existing S3 key as `source_document_key`. Identical to Flow A from `experiment_starter` onwards.

The old browser-orchestrated flow (N presign uploads + in-browser `/gold-compare` call) no longer exists. The `/gold-compare` endpoint remains deployed but is not called by the frontend.

---

## Flow A — gold.html (Browser-Initiated)

### A0. Prerequisites — Page Load and Auth

**File:** `frontend/gold.html`, `frontend/gold.js`

On load, `init()` checks `localStorage` for a valid `id_token`. Silent refresh is attempted via the Cognito token endpoint (`/oauth2/token`, grant_type `refresh_token`) if the token is expired. If that fails, the auth panel is shown.

Tokens stored in `localStorage`: `id_token`, `access_token`, `refresh_token`.

The Run button is disabled until both files are chosen and run count is valid (`gold.js:126`):
- **Document file** (`.txt`, `.md`, `.csv`, `.pdf`) — the medical document to summarise
- **Reference file** (`.txt`, `.md`) — the gold standard to score against

Run count: 2–100.

---

### A1. Presign — Single Upload

**Function:** `uploadDocument()` (`gold.js:136`)  
**API:** `POST /presign` → `api_presign` Lambda (`lambda/api_presign/handler.py`)

Called once for the source document.

#### Quota check
**Read/Write:** DynamoDB `jobs` table, key `quota#{user_id}#{today}`  
Atomically increments `count`, sets TTL at midnight UTC. Returns 429 if `count >= daily_limit` (default 20).

#### Job record creation
**Write:** DynamoDB `jobs` table
```
job_id:     uuid4
user_id:    Cognito JWT sub
status:     PENDING
created_at: UTC ISO timestamp
filename:   sanitised filename
```

#### Presigned POST URL
Generates S3 presigned POST for `uploads/{job_id}/{filename}`. TTL 300s.

**Response to browser:** `{job_id, presign_url, presign_fields}`

`uploadDocument()` returns `"uploads/{job_id}/{file.name}"` — this becomes `source_document_key` for the experiment.

---

### A2. S3 Upload — Single

**Trigger:** Presign response received  
**Write:** S3 uploads bucket, `uploads/{job_id}/{filename}`

Browser constructs `FormData` with all `presign_fields` first, file last (required by S3 policy). POSTs directly to S3, bypassing API Gateway.

This upload fires an S3 `ObjectCreated` event which triggers `pipeline_starter`. That pipeline run has **no experiment context** — the job record has no `experiment_id` or `run_number`. Its summary is written to `summaries/{job_id}/summary.txt` but is not accessible via the user-facing API (the `user_id` is the actual user's Cognito sub, but the job is not linked to any experiment). This "seed" run is a side effect of needing to land the document in S3 and its output is not included in experiment results.

---

### A3. Start Experiment

**Function:** `startExperiment()` (`gold.js:168`)  
**API:** `POST /experiments` → `experiment_starter` Lambda

Generates a UUID v4 `experimentId` client-side via `crypto.randomUUID()`. Reads the reference file text and sends it as `gold_text`.

**Request body:**
```json
{
  "experiment_id": "<uuid>",
  "expected_n": N,
  "source_document_key": "uploads/{job_id}/{filename}",
  "gold_text": "<reference text from browser>"
}
```

For the full server-side handling of this request, see [Flow B, step B0](#b0-caller--post-experiments).

`startExperiment()` returns `experimentId` on success.

---

### A4. Pipeline Runs (Server-Side)

`experiment_starter` copies the source document N times in a loop. Each S3 copy triggers `pipeline_starter` → pipeline Express SM. All N runs execute in parallel without further browser involvement.

For full detail see [Flow B, steps B1–B2](#b1-pipeline-starter--per-run-n-times-in-parallel).

When the last run completes, `renderer` starts the comparison STANDARD state machine. See [Flow B, step B3](#b3-comparison-state-machine).

---

### A5. Poll Experiment Status

**Function:** `pollExperiment()` (`gold.js:192`)  
**API:** `GET /experiments/{experimentId}` → `api_experiment_status` Lambda (`lambda/api_experiment_status/handler.py`)  
**Interval:** 10s. **Timeout:** 180 ticks × 10s = 30 minutes.

Each tick:

**Read:** DynamoDB `experiments` table — `GetItem` by `experiment_id`  
Returns: `experiment_id`, `status`, `expected_n`, `completed_n`, `successful_n`, `created_at`, `completed_at?`, `error_message?`

If `status == COMPLETED`:  
**Read:** S3 summaries bucket — `experiments/{experimentId}/report/comparison.json`  
**Read:** S3 summaries bucket — `experiments/{experimentId}/report/narrative.md`  
Appended to response as `report` and `narrative`.

Header is updated each tick: `"Runs complete: {completed_n} / {expectedN} — comparing…"`

Terminal states:
- `COMPLETED` → returns full data payload, polling ends
- `COMPARISON_FAILED` → throws with `data.error_message`
- 180 ticks elapsed → throws `"Timed out after 30 minutes"`

---

### A6. Results Display and Download

**Trigger:** `pollExperiment()` resolves

**Zip download** — `buildAndDownloadZip()` (`gold.js:394`) — triggers automatically:

| File in zip | Content |
|-------------|---------|
| `reference.txt` | The reference text supplied by the user |
| `gold_report.txt` | Client-side text report built from `experimentResult.report` — gold scores, variance stats, per-run table |
| `comparison.json` | `experimentResult.report` — full comparison SM output (variance_results, gold_results, doc_type, etc.) |
| `narrative.md` | `experimentResult.narrative` — the Claude-generated Markdown analysis from `report_generator` |

**Results panel** — `showGoldPanel()` (`gold.js:233`):

Reads `experimentResult.report.gold_results`. Displays:
- Summary stat cards: Titan embedding cosine mean/min/max/std, BERTScore F1 mean/min/max/std
- Per-run score table keyed by `gold_results.embedding_cosine.run_numbers`, colour-coded (≥0.8 green, ≥0.6 amber)

Individual run summaries are not displayed or included in the zip. They are stored server-side at `experiments/{id}/runs/{n}/summary.txt` but are not accessible via the API (experiment job records have `user_id: "experiment"`, so `GET /summaries/{jobId}` returns 404 on the ownership check).

---

---

## Flow B — Direct API Call (Programmatic)

### B0. Caller — `POST /experiments`

**Lambda:** `experiment_starter` (`lambda/experiment_starter/handler.py`)  
**Trigger:** `POST /experiments` with JWT auth. Called by the gold.html frontend via `startExperiment()` (Flow A) and directly by programmatic callers (Flow B).

**Request body:**
```json
{
  "experiment_id": "variance-test-001",
  "expected_n": 10,
  "source_document_key": "uploads/{existing-job-id}/{filename}",
  "gold_text": "optional reference summary text",
  "config": {"description": "..."}
}
```

Constraints: `expected_n` 2–100, `source_document_key` must exist in the uploads bucket.

#### Source document verification
**Read:** S3 uploads bucket — `head_object` on `source_document_key`. Returns 404 if absent.

#### Gold text persistence (if provided)
**Write:** S3 summaries bucket — `experiments/{experiment_id}/gold.txt`

#### Experiment config
**Write:** S3 summaries bucket — `experiments/{experiment_id}/config.json`
```json
{
  "experiment_id": "...", "expected_n": N,
  "config": {"source_document_key": "...", "gold_key": "experiments/.../gold.txt", ...},
  "created_at": "..."
}
```

#### Experiment record
**Write:** DynamoDB `experiments` table
```
experiment_id: "..."
expected_n:    N (Decimal)
completed_n:   0
successful_n:  0
failed_n:      0
status:        PENDING
config:        {source_document_key, gold_key, ...}
created_at:    UTC ISO timestamp
```

#### Per-run job creation and S3 copy (loop N times)

For each run number 1…N:

**Write:** DynamoDB `jobs` table
```
job_id:        uuid4
experiment_id: "..."
run_number:    N (Decimal)
status:        PENDING
created_at:    UTC ISO timestamp
user_id:       "experiment"
```

**Write:** S3 uploads bucket — `s3.copy_object()` from `source_document_key` to `uploads/{job_id}/{source_filename}`  
This S3 copy immediately fires an `ObjectCreated` event, triggering `pipeline_starter` for each run simultaneously (no stagger).

**Response:** `{experiment_id, job_ids: [...], expected_n: N}`

---

### B1. Pipeline Starter — Per Run (N times in parallel)

**Lambda:** `pipeline_starter` (`lambda/pipeline_starter/handler.py`)  
**Trigger:** S3 `ObjectCreated:*` event from each `copy_object` above

**Read:** DynamoDB `jobs` table — `ProjectionExpression='experiment_id, run_number'`  
Both fields are present (written by `experiment_starter`).

**Write:** Step Functions — starts pipeline EXPRESS execution with experiment context in input:
```json
{
  "job_id": "...", "bucket": "...", "key": "uploads/{job_id}/{filename}",
  "experiment_id": "variance-test-001", "run_number": 3
}
```

**Write:** DynamoDB `jobs` table — conditional `SET status = RUNNING WHERE status = PENDING`

---

### B2. Document Pipeline State Machine — Per Run

Identical to the pipeline flow (ClassifyDocument → ExtractData → ValidateData) with the same S3 reads, Bedrock calls, and data shapes.

The only difference is in **RenderSummary**:

#### State 1: ClassifyDocument → `classifier`

**Input:** `{job_id, bucket, key, experiment_id, run_number}`

**Read:** S3 uploads bucket — raw document text  
**Read:** Bedrock Prompt Management — classifier system prompt via `bedrock-agent.get_prompt()`  
**Bedrock call:** `bedrock-runtime.converse()` — Claude Haiku, `maxTokens=20`, `temperature=0`, guardrail optionally applied  

Validates response against hardcoded set: `{lab_result, doctors_notes, injury_doc, visit_assessment, psych_eval}`

**Output:**
```json
{"job_id": "...", "bucket": "...", "key": "...", "doc_type": "lab_result",
 "experiment_id": "...", "run_number": N,
 "usage_stats": {"classifier": {"model": "...", "input_tokens": N, "output_tokens": N}}}
```
**Next:** ExtractData

#### State 2: ExtractData → `extractor`

**Read:** S3 uploads bucket — document text fetched again (PHI never passes through SFN execution state)  
**Read:** Bedrock Prompt Management — doc-type-specific extraction prompt  
**Read:** Bundled `schemas/{doc_type}_schema.json`  
**Bedrock call:** `bedrock-runtime.converse()` — Claude Sonnet, forced tool use, `maxTokens=4096`, `temperature=0`

**Next:** ValidateData

#### State 3: ValidateData → `validator`

**Read:** Bundled `schemas/{doc_type}_schema.json`  
`jsonschema.validate()` — no AWS calls.

**Next:** RenderSummary

#### State 4: RenderSummary → `renderer` (experiment path)

After writing the standard `summaries/{job_id}/summary.txt` and `usage.json` and updating DynamoDB `jobs` to COMPLETED, the renderer detects `experiment_id` in the event and calls two additional functions:

**`_write_experiment_outputs()`**

**Write:** S3 summaries bucket
- `experiments/{experiment_id}/runs/{run_number}/summary.txt` — the rendered summary text
- `experiments/{experiment_id}/runs/{run_number}/metadata.json`:
  ```json
  {
    "experiment_id": "...", "run_number": N, "job_id": "...",
    "source_document_key": "...", "doc_type": "...",
    "classification": {"model_id": "...", "prompt_arn": "...", "prompt_version": "...",
                       "guardrail_id": "...", "guardrail_version": "...",
                       "input_tokens": N, "output_tokens": N},
    "extraction":   {"model_id": "...", "prompt_arn": "...", "prompt_version": "...",
                     "input_tokens": N, "output_tokens": N},
    "timestamp": "..."
  }
  ```

**`_record_experiment_success()`**

**Write:** DynamoDB `experiments` table — atomic `ADD completed_n :1, successful_n :1`, returns `ALL_NEW`  
**Read:** Response attributes — checks if `completed_n >= expected_n`

If all runs are done, calls `_maybe_start_comparison()`:

**Write:** Step Functions — starts the comparison STANDARD execution, name=`experiment_id` (`ExecutionAlreadyExists` treated as no-op in case two runs complete simultaneously)

Comparison SM execution input:
```json
{
  "experiment_id": "variance-test-001",
  "summaries_bucket": "...",
  "expected_n": 10,
  "successful_n": 9
}
```

#### Error path: MarkJobFailed → `fail_handler`

**Trigger:** Any `Catch` block; `ResultPath: "$.error"` preserves `job_id` at top level  
**Write:** DynamoDB `jobs` table — `SET status = FAILED, error_message = ...` (truncated to 1000 chars)  
**Next:** JobFailed (Fail terminal)

---

### B3. Comparison State Machine

**Definition:** `infra/comparison_sm.json.tpl`  
**Type:** STANDARD (not EXPRESS — execution history persists, can be inspected)  
**Logging:** ERROR only, `include_execution_data = false`

Unlike the pipeline SM, several states use `ResultPath` to merge their output into the accumulated state rather than replacing it:
- `ComputeVariance` → `ResultPath: "$.variance_results"`
- `ComputeGoldAccuracy` → `ResultPath: "$.gold_results"`
- `GenerateReport` → `ResultPath: "$.report"`

This means the full accumulated state (`experiment_id`, `config`, `run_manifests`, `variance_results`, `gold_results`, `report`) is all available to `WriteReport` at the end.

Every state has `Catch` on `States.ALL` → `MarkComparisonFailed` with `ResultPath: "$.error"`.

---

#### State 1: CollectSummaries → `summary_collector`

**Input:** `{experiment_id, summaries_bucket, expected_n, successful_n}`

**Read:** DynamoDB `experiments` table — fetches `config` (contains `gold_key`)  
**Read:** S3 summaries bucket — paginates `list_objects_v2` on prefix `experiments/{experiment_id}/runs/`, finds all `summary.txt` files, builds run manifest  
**Read:** S3 summaries bucket — reads `metadata.json` from the first run to determine `doc_type`

Summary text is never loaded here — only S3 key paths are returned. PHI stays in S3.

**Output (replaces full state):**
```json
{
  "experiment_id": "...",
  "summaries_bucket": "...",
  "run_manifests": [
    {"run_number": 1, "summary_key": "experiments/.../runs/1/summary.txt",
     "metadata_key": "experiments/.../runs/1/metadata.json"},
    ...
  ],
  "config": {"source_document_key": "...", "gold_key": "experiments/.../gold.txt", ...},
  "has_gold": true,
  "gold_key": "experiments/.../gold.txt",
  "successful_n": 9,
  "doc_type": "lab_result"
}
```
**Next:** ComputeVariance

---

#### State 2: ComputeVariance → `variance_scorer`

**Input:** full CollectSummaries output  
**ResultPath:** `$.variance_results` (merged into state, does not replace it)

**Read:** S3 summaries bucket — reads each `summary_key` from `run_manifests` sequentially  
**Bedrock calls:** Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`, 1024 dims, normalised) for each summary, fetched in parallel via `ThreadPoolExecutor`

Computes:
- **Embedding cosine similarity matrix** — dot product between all pairs (valid because Titan normalises)
- **TF-IDF cosine similarity matrix** — tokenised (`\b[a-z]{2,}\b`), IDF-weighted, L2-normalised, dot product

**Output (merged as `$.variance_results`):**
```json
{
  "embedding_cosine": {
    "matrix": [[...]], "run_numbers": [1, 2, ...],
    "n_runs": N, "n_pairs": M, "mean": ..., "min": ..., "max": ..., "std": ..., "variance": ...
  },
  "tfidf_cosine": { /* same shape */ }
}
```
**Next:** CheckHasGold

---

#### State 3: CheckHasGold (Choice)

**Type:** Choice — no Lambda invoked

Evaluates `$.has_gold`:
- `true` → ComputeGoldAccuracy
- `false` (default) → GenerateReport

---

#### State 4: ComputeGoldAccuracy → `gold_scorer` (conditional)

**Input:** full accumulated state including `variance_results`  
**ResultPath:** `$.gold_results`

**Read:** S3 summaries bucket — `gold_key` (reference text)  
**Read:** S3 summaries bucket — each `summary_key` from `run_manifests`  
**Bedrock calls:** Titan embeddings for each summary + the reference, in parallel via `ThreadPoolExecutor`

BERTScore via `allenai/scibert_scivocab_uncased`, 8 layers, CPU, `batch_size=8`.  
Tokenizer capped at **512** tokens (higher than the now-unused API Gateway version's 256 — Step Functions timeout is 300s, allowing higher accuracy for longer texts).

**Output (merged as `$.gold_results`):**
```json
{
  "embedding_cosine": {
    "scores": [0.912, ...], "run_numbers": [1, 2, ...],
    "mean": ..., "min": ..., "max": ..., "std": ..., "n": N
  },
  "bertscore_f1": { /* same shape */ }
}
```
**Next:** GenerateReport

---

#### State 5: GenerateReport → `report_generator`

**Input:** full accumulated state (`experiment_id`, `config`, `doc_type`, `successful_n`, `variance_results`, `gold_results` if present)  
**ResultPath:** `$.report`

Builds a stats block from the numeric scores only — summary texts are never passed here. PHI-safe.

**Bedrock call:** `bedrock-runtime.converse()` — Claude Sonnet (`us.anthropic.claude-sonnet-4-6`), `maxTokens=1024`, `temperature=0.3`

Prompt instructs Claude to write a 200–400 word Markdown analysis covering: inter-run consistency, gold accuracy (if present), outlier runs, and an overall reliability verdict.

**Output (merged as `$.report`):**
```json
{"narrative_md": "## Summary\n\n..."}
```
**Next:** WriteReport

---

#### State 6: WriteReport → `report_writer`

**Input:** full accumulated state including all results and `$.report`

**Write:** S3 summaries bucket
- `experiments/{experiment_id}/report/comparison.json`:
  ```json
  {
    "experiment_id": "...", "completed_at": "...", "doc_type": "...",
    "successful_n": N, "config": {...},
    "variance_results": {...}, "gold_results": {...}
  }
  ```
- `experiments/{experiment_id}/report/narrative.md` — the Claude-generated Markdown report

**Write:** DynamoDB `experiments` table — `SET status = COMPLETED, completed_at = ...`

**Output:** `{experiment_id, report_prefix: "experiments/.../report/"}`  
**Next:** ComparisonComplete (Succeed)

---

#### Error path: MarkComparisonFailed → `comparison_fail_handler`

**Trigger:** Any `Catch` block; `ResultPath: "$.error"` preserves `experiment_id` at top level  
**Write:** DynamoDB `experiments` table — `SET status = COMPARISON_FAILED, error_message = ...` (truncated to 1000 chars)  
**Next:** ComparisonFailed (Fail terminal)

---

## Data Stores Summary

| Store | Key pattern | Written by | Read by | Retention |
|-------|-------------|-----------|---------|-----------|
| DynamoDB `jobs` | `job_id` (hash) | `api_presign` (PENDING), `experiment_starter` (PENDING+experiment fields), `pipeline_starter` (RUNNING), `renderer` (COMPLETED), `fail_handler` (FAILED) | `pipeline_starter`, `api_status`, `api_summary` | Quota records TTL at midnight; job records no TTL |
| DynamoDB `experiments` | `experiment_id` (hash) | `experiment_starter` (PENDING), `renderer` (increments counters), `report_writer` (COMPLETED), `comparison_fail_handler` (COMPARISON_FAILED) | `summary_collector`, `api_experiment_status` | No TTL |
| S3 uploads bucket | `uploads/{job_id}/{filename}` | Browser (presign POST) or `experiment_starter` (copy_object) | `pipeline_starter` (experiment context only), `classifier`, `extractor` | 30-day lifecycle expiry |
| S3 summaries bucket | `summaries/{job_id}/summary.txt` | `renderer` | `api_summary` | 90-day lifecycle expiry |
| S3 summaries bucket | `summaries/{job_id}/usage.json` | `renderer` | `api_summary` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/gold.txt` | `experiment_starter` | `gold_scorer` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/config.json` | `experiment_starter` | — (informational) | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/runs/{n}/summary.txt` | `renderer` | `variance_scorer`, `gold_scorer` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/runs/{n}/metadata.json` | `renderer` | `summary_collector` (first run only, for doc_type) | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/report/comparison.json` | `report_writer` | `api_experiment_status`, zip download | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/report/narrative.md` | `report_writer` | `api_experiment_status`, zip download | 90-day lifecycle expiry |
| Browser memory | — | Browser (reference text read from reference file) | `experiment_starter` (sent as `gold_text` in POST body); zip builder | Cleared on page unload |
| Zip download | Local filesystem | JSZip (client-side) | User | Indefinite (local file) |

---

## Key Architectural Differences Between the Two Flows

| | Flow A (gold.html) | Flow B (direct API call) |
|---|---|---|
| Trigger | User clicks Run Test in browser | `POST /experiments` with existing S3 key |
| Document ingestion | Browser presign-uploads document; `experiment_starter` copies that S3 object N times | Caller provides `source_document_key`; `experiment_starter` copies it N times |
| Side effect | One untracked "seed" pipeline run fires on upload (output not in experiment results) | None |
| Comparison triggered by | `renderer` (when `completed_n >= expected_n`) | Same |
| Comparison runs on | Comparison SM (STANDARD), 300s timeout | Same |
| BERTScore token limit | 512 (`gold_scorer`, Step Functions constraint) | Same |
| Results stored | S3 + DynamoDB + client-side zip auto-downloaded | S3 + DynamoDB |
| Results accessed by | Browser polls `api_experiment_status` every 10s; zip triggered on completion | Caller polls `GET /experiments/{experimentId}` |
| State machine types | Pipeline: EXPRESS; Comparison: STANDARD | Same |
