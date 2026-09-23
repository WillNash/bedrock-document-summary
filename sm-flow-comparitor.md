# Comparison Flows — Complete Step-by-Step Breakdown

There are two distinct flows depending on how the comparison is initiated:

- **Flow A — gold.html (browser-driven):** User uploads a document and reference file through the existing UI. The pipeline runs N times, the browser collects summaries and calls `POST /gold-compare` directly. The comparison state machine is NOT involved.
- **Flow B — experiment API (server-driven):** Caller POSTs to `POST /experiments`. The source document is already in S3 and is copied N times server-side. When all pipeline runs complete, the renderer automatically triggers the comparison state machine.

The comparison state machine (`infra/comparison_sm.json.tpl`) is only used in Flow B. The frontend has not yet been updated to call `POST /experiments`.

---

## Flow A — gold.html (Browser-Driven)

### A0. Prerequisites — Page Load and Auth

**File:** `frontend/gold.html`, `frontend/gold.js`

On load, `init()` (`gold.js:603`) checks `localStorage` for a valid `id_token`. Silent refresh is attempted via the Cognito token endpoint (`/oauth2/token`, grant_type `refresh_token`) if the token is expired. If that fails, the auth panel is shown.

Tokens stored in `localStorage`: `id_token`, `access_token`, `refresh_token`.

The Run button is disabled until both files are chosen (`gold.js:123`):
- **Document file** (`.txt`, `.md`, `.csv`, `.pdf`) — the medical document to summarise
- **Reference file** (`.txt`, `.md`) — the gold standard to score against

The reference file is read into browser memory immediately on selection (`gold.js:501`). It is never uploaded to S3.

---

### A1. Presign — Per Run (N times, staggered 200ms)

**Function:** `submitJob()` (`gold.js:174`)  
**API:** `POST /presign` → `api_presign` Lambda (`lambda/api_presign/handler.py`)

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
Generates S3 presigned POST for `uploads/{job_id}/{filename}`. TTL 300s. Content-Type condition: `starts-with ''`.

**Response to browser:** `{job_id, presign_url, presign_fields}`

---

### A2. S3 Upload — Per Run

**Trigger:** Presign response received  
**Write:** S3 uploads bucket, `uploads/{job_id}/{filename}`

Browser constructs `FormData` with all `presign_fields` first, file last (required by S3 policy). POSTs directly to S3, bypassing API Gateway.

Uploads bucket: KMS encrypted (PHI CMK), versioned, 30-day lifecycle expiry on `uploads/` prefix.

---

### A3. Pipeline Starter — Per Run

**Lambda:** `pipeline_starter` (`lambda/pipeline_starter/handler.py`)  
**Trigger:** S3 `ObjectCreated:*` event on `uploads/` prefix

Parses `job_id` from key (`uploads/{job_id}/{filename}`).

**Read:** DynamoDB `jobs` table — fetches `experiment_id` and `run_number` from the job record. For Flow A these are absent, so execution input will not include experiment context.

**Write:** Step Functions — starts pipeline EXPRESS execution, name=`job_id` (deduplication: `ExecutionAlreadyExists` treated as no-op)

Execution input:
```json
{"job_id": "...", "bucket": "...", "key": "uploads/{job_id}/{filename}"}
```

**Write:** DynamoDB `jobs` table — conditional `SET status = RUNNING WHERE status = PENDING`

---

### A4. Document Pipeline State Machine

**Definition:** `infra/state_machine.json.tpl`  
**Type:** EXPRESS  
**Logging:** ERROR only, `include_execution_data = false`

Each state's return value becomes the full input to the next state. Every processing state has `Retry` on transient Lambda errors and `Catch` on `States.ALL` → `MarkJobFailed` with `ResultPath: "$.error"` (merges error into existing input, preserving `job_id` at top level).

#### State 1: ClassifyDocument → `classifier`

**Input:** `{job_id, bucket, key}`

**Read:** S3 uploads bucket — raw document text  
**Read:** Bedrock Prompt Management — classifier system prompt via `bedrock-agent.get_prompt()`  
**Bedrock call:** `bedrock-runtime.converse()` — Claude Haiku, `maxTokens=20`, `temperature=0`, guardrail optionally applied  

Validates response against hardcoded set: `{lab_result, doctors_notes, injury_doc, visit_assessment, psych_eval}`

**Output:**
```json
{"job_id": "...", "bucket": "...", "key": "...", "doc_type": "lab_result",
 "usage_stats": {"classifier": {"model": "...", "input_tokens": N, "output_tokens": N}}}
```
**Next:** ExtractData

#### State 2: ExtractData → `extractor`

**Input:** classifier output above

**Read:** S3 uploads bucket — document text fetched again (not passed through execution state to keep PHI out of Step Functions logs)  
**Read:** Bedrock Prompt Management — doc-type-specific extraction prompt  
**Read:** Bundled `schemas/{doc_type}_schema.json` (included in Lambda zip at build time)  
**Bedrock call:** `bedrock-runtime.converse()` — Claude Sonnet, forced tool use (`toolChoice: {tool: {name: "extract_document"}}`), `maxTokens=4096`, `temperature=0`

Extracts `toolUse.input` from response.

**Output:**
```json
{"job_id": "...", "bucket": "...", "key": "...", "doc_type": "...",
 "extracted_data": {}, "usage_stats": {"classifier": {...}, "extractor": {...}}}
```
**Next:** ValidateData

#### State 3: ValidateData → `validator`

**Input:** extractor output above

**Read:** Bundled `schemas/{doc_type}_schema.json`  
`jsonschema.validate()` — no AWS calls. Raises on failure → `Catch` → `MarkJobFailed`.

Renames `extracted_data` → `validated_data`.

**Output:**
```json
{"job_id": "...", "bucket": "...", "key": "...", "doc_type": "...",
 "validated_data": {}, "usage_stats": {...}}
```
**Next:** RenderSummary

#### State 4: RenderSummary → `renderer`

**Input:** validator output above

**Read:** Bundled `templates/{doc_type}.j2` — Jinja2 template  
Renders `template.render(**validated_data)`.

**Write:** S3 summaries bucket
- `summaries/{job_id}/summary.txt`
- `summaries/{job_id}/usage.json`

**Write:** DynamoDB `jobs` table — `SET status = COMPLETED, doc_type = ..., completed_at = ...`

Checks `event.get('experiment_id')` — absent in Flow A, so no experiment writes and no comparison SM trigger.

**Output:** `{job_id, summary_key}`  
**Next:** JobComplete (Succeed)

#### Error path: MarkJobFailed → `fail_handler`

**Trigger:** Any `Catch` block; `ResultPath: "$.error"` preserves `job_id` at top level  
**Write:** DynamoDB `jobs` table — `SET status = FAILED, error_message = ...` (truncated to 1000 chars)  
**Next:** JobFailed (Fail terminal)

---

### A5. Browser Polling — Per Run

**Function:** `pollUntilDone()` (`gold.js:203`)  
All N jobs polled in parallel. Each tick: wait 5s, then:

**`GET /jobs/{jobId}` → `api_status`**  
**Read:** DynamoDB `jobs` table — ownership check (404 if `user_id` mismatch)  
Returns: `{job_id, status, doc_type?, error_message?, completed_at?}`

On `COMPLETED`:  
**`GET /summaries/{jobId}` → `api_summary`**  
**Read:** DynamoDB `jobs` table — ownership + status check  
**Read:** S3 summaries bucket — `summaries/{job_id}/summary.txt` and `usage.json`  
Returns: `{job_id, doc_type, summary, usage}`

Summary text held in browser memory. Timeout: 120 × 5s = 10 minutes.

---

### A6. Gold Comparison — Direct Lambda Call

**Function:** `runGoldComparison()` (`gold.js:240`)  
**Trigger:** All polls settle, ≥1 succeeded  
**API:** `POST /gold-compare` → `gold_comparator` Lambda (Docker image, 5120 MB, 300s timeout)

**Request:**
```json
{"texts": ["summary 1", ...], "reference": "gold reference text from browser memory"}
```
Limits: texts 2–200; BERTScore capped at 20 (CPU constraint).

**Cold start handling:** 503 on first attempt → waits 60s → retries once. SciBERT model loads at module level and can exceed API Gateway's 29s timeout on cold start.

**Lambda processing:**  
- Titan embeddings for each summary + reference, fetched in parallel via `ThreadPoolExecutor`
- Cosine similarity = dot product (Titan normalises vectors)
- BERTScore F1 via `allenai/scibert_scivocab_uncased`, 8 layers, CPU. Tokenizer capped at **256** tokens (keeps inference under 29s API Gateway limit — BERT attention is O(n²))

**Response:**
```json
{
  "embedding_cosine": {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": N},
  "bertscore_f1":     {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": N}
}
```

---

### A7. Output — Client-Side Zip

All assembly is client-side using JSZip. Nothing written server-side beyond what the pipeline already produced.

| File in zip | Content |
|-------------|---------|
| `summary_01.txt` … `summary_N.txt` | Individual pipeline summaries |
| `manifest.txt` | Per-run OK/FAILED status |
| `usage_report.txt` | Token usage per run per stage, model IDs, grand totals |
| `reference.txt` | The reference file supplied by the user |
| `gold_comparison.json` | Raw comparator response (if scoring succeeded) |
| `gold_comparison_report.txt` | Human-readable accuracy report with per-run scores |

Inline panel shows embedding cosine and BERTScore F1 stats + per-run score table (colour-coded ≥0.8 green, ≥0.6 amber).

---

---

## Flow B — Experiment API (Server-Driven, Comparison State Machine)

### B0. Caller — `POST /experiments`

**Lambda:** `experiment_starter` (`lambda/experiment_starter/handler.py`)  
**Trigger:** Direct API call with JWT auth (no frontend page currently calls this)

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

Identical to Flow A steps A4 (ClassifyDocument → ExtractData → ValidateData) with the same S3 reads, Bedrock calls, and data shapes.

The only difference is in **RenderSummary**:

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
Tokenizer capped at **512** tokens (higher than the API Gateway version's 256 because Step Functions timeout is 300s, not 29s — allows higher accuracy for longer texts).

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
| DynamoDB `experiments` | `experiment_id` (hash) | `experiment_starter` (PENDING), `renderer` (increments counters), `report_writer` (COMPLETED), `comparison_fail_handler` (COMPARISON_FAILED) | `summary_collector` | No TTL |
| S3 uploads bucket | `uploads/{job_id}/{filename}` | Browser (presign POST) or `experiment_starter` (copy_object) | `pipeline_starter` (experiment context only), `classifier`, `extractor` | 30-day lifecycle expiry |
| S3 summaries bucket | `summaries/{job_id}/summary.txt` | `renderer` | `api_summary` | 90-day lifecycle expiry |
| S3 summaries bucket | `summaries/{job_id}/usage.json` | `renderer` | `api_summary` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/gold.txt` | `experiment_starter` | `gold_scorer` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/config.json` | `experiment_starter` | — (informational) | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/runs/{n}/summary.txt` | `renderer` | `variance_scorer`, `gold_scorer` | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/runs/{n}/metadata.json` | `renderer` | `summary_collector` (first run only, for doc_type) | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/report/comparison.json` | `report_writer` | External / caller | 90-day lifecycle expiry |
| S3 summaries bucket | `experiments/{id}/report/narrative.md` | `report_writer` | External / caller | 90-day lifecycle expiry |
| Browser memory | — | Browser (reference text, summaries collected via poll) | `gold_comparator` (via POST body) | Cleared on page unload |
| Zip download | Local filesystem | JSZip (client-side, Flow A only) | User | Indefinite (local file) |

---

## Key Architectural Differences Between the Two Flows

| | Flow A (gold.html) | Flow B (experiment API) |
|---|---|---|
| Trigger | User clicks Run Test in browser | `POST /experiments` API call |
| Document ingestion | Browser uploads via presigned POST | `experiment_starter` copies existing S3 object |
| Comparison triggered by | Browser (after polling all jobs) | `renderer` (when `completed_n >= expected_n`) |
| Comparison runs on | `gold_comparator` Lambda, API Gateway, 29s limit | Comparison state machine, 300s timeout |
| BERTScore token limit | 256 (API Gateway constraint) | 512 (Step Functions constraint, more accurate) |
| Results stored | Client-side zip download only | S3 + DynamoDB (persistent) |
| State machine type | Pipeline: EXPRESS | Pipeline: EXPRESS; Comparison: STANDARD |
| Failure visibility | Browser error message | DynamoDB `experiments.status = COMPARISON_FAILED` |
