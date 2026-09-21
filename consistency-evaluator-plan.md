# Architecture Plan

## Context Summary

Build variability quantification for the medical document summarization pipeline: a standalone CLI tool (`tools/consistency_evaluator.py`) that makes real Bedrock calls with temperature override, and a pytest harness (`tests/test_consistency.py`) that mocks Bedrock responses to test the similarity computation and aggregation logic in CI. The feature measures output consistency across N runs using sentence-embedding cosine similarity, BERTScore F1, and TF-IDF cosine as a lightweight baseline — applied to both the structured JSON layer (`extracted_data`) and the rendered text layer (Jinja2 summary string).

## Two-Pathway Architecture Constraint

This feature is **pathway 1 of 2**. A future pathway 2 will independently measure N outputs against a gold standard reference. These are separate, non-overlapping concerns:

- **Pathway 1 — Variability** (this task): N outputs → pairwise N×N similarity matrix → mean/min/std/cv. No reference. Answers: "how much does the pipeline vary?"
- **Pathway 2 — Gold standard** (future): N outputs + 1 reference → N individual similarity scores → mean/min/std against the reference. Answers: "how accurate is the pipeline?"

**Implementation constraints to enforce this separation:**
1. **No mixed function signatures.** Variability functions must not accept an optional `reference` parameter — that would couple the two pathways. Pathway 2 will have its own separate functions and its own CLI tool or subcommand.
2. **N-run collection must be a standalone reusable function.** `_collect_runs()` (or equivalent) is the only shared infrastructure between the two pathways. Extract it cleanly from `run_evaluation()` so pathway 2 can call it without inheriting pathway 1's similarity logic.
3. **Name things accurately.** `consistency_evaluator.py` is pathway 1 only. Pathway 2 will be `gold_standard_evaluator.py` or a clearly separated CLI subcommand. Do not name anything in this task in a way that implies it covers both pathways.

## Decision: Option (c) — Both

The CLI tool and the test harness serve orthogonal purposes that cannot be collapsed:

- `tools/consistency_evaluator.py` makes real Bedrock calls with `temperature=0.7` and is the production artifact for actual pipeline evaluation. It cannot run in CI because it requires live AWS credentials and Bedrock access.
- `tests/test_consistency.py` mocks Bedrock and uses deliberately varied synthetic responses to validate that the similarity measurement and aggregation functions are correct. It runs in CI with no AWS credentials.

Both are required to satisfy the goal. Neither replaces the other.

---

## Impacted Files

### New files to create

- `/workspace/active_repo/tools/consistency_evaluator.py` — standalone CLI tool
- `/workspace/active_repo/tests/test_consistency.py` — pytest harness for similarity infrastructure

### Existing files to modify

- `/workspace/active_repo/tools/requirements.txt` — APPEND new dependencies; do NOT replace the file. The existing `python-hcl2==8.1.4` line must be preserved.
- `/workspace/active_repo/.github/workflows/ci.yml` — add install steps for test-only similarity deps (sentence-transformers, bert-score, scikit-learn, rouge-score, numpy) with explicit CPU-only torch install

### Files referenced but NOT modified

- `/workspace/active_repo/lambda/extractor/handler.py` — read for architecture reference; the CLI calls Bedrock directly rather than modifying the handler
- `/workspace/active_repo/lambda/renderer/handler.py` — read for architecture reference; the CLI reuses Jinja2 rendering logic inline
- `/workspace/active_repo/lambda/classifier/handler.py` — read for architecture reference only
- `/workspace/active_repo/lambda/validator/handler.py` — read for architecture reference only
- `/workspace/active_repo/schemas/*.json` — read at runtime by the CLI and test fixtures
- `/workspace/active_repo/templates/*.j2` — read at runtime by the CLI and test fixtures

---

## Step-by-Step Execution Plan

### Step 1: Update `tools/requirements.txt`

APPEND the following lines to the existing file. Do NOT overwrite it. The file currently contains only `python-hcl2==8.1.4`, which must remain.

Lines to append:
```
sentence-transformers>=6.1.0
bert-score==0.3.13
scikit-learn>=1.4.0
rouge-score>=0.1.2
numpy>=1.26.0
torch>=2.2.0
jinja2>=3.1.0
jsonschema>=4.21.0
```

Notes:
- `sentence-transformers>=6.1.0` reflects the verifier correction (v6.1.0 released 2026-09-18).
- `bert-score==0.3.13` is pinned because it is the last release and effectively unmaintained.
- `torch>=2.2.0` is required by sentence-transformers v6.x; in CI it must be installed as CPU-only (see Step 2).
- `jinja2` and `jsonschema` are already in `lambda/requirements.txt` but not `tools/requirements.txt`; they are needed by the CLI to render summaries locally.

### Step 2: Update `.github/workflows/ci.yml` — add similarity deps install step

The existing CI step installs only `pytest boto3 jinja2 jsonschema`. The new `tests/test_consistency.py` requires `torch` (CPU-only), `sentence-transformers`, `bert-score`, `scikit-learn`, `rouge-score`, and `numpy`.

Add TWO new steps after the existing "Install test dependencies" step, before "Run tests":

```yaml
- name: Install CPU-only torch (prevents 2-3 GB CUDA wheel download)
  run: pip install torch --index-url https://download.pytorch.org/whl/cpu

- name: Install similarity test dependencies
  run: pip install "sentence-transformers>=6.1.0" "bert-score==0.3.13" "scikit-learn>=1.4.0" "rouge-score>=0.1.2" "numpy>=1.26.0"
```

The torch CPU-only step MUST come first. If sentence-transformers is installed before torch is pinned to CPU, pip's dependency resolver may pull a 2-3 GB CUDA wheel on `ubuntu-latest`.

Also add a cache step for HuggingFace model downloads, keyed on model names used in tests, to avoid repeated large downloads:

```yaml
- name: Cache HuggingFace models
  uses: actions/cache@v4
  with:
    path: ~/.cache/huggingface/hub
    key: hf-models-all-minilm-distilbert
```

This cache step should be placed before the similarity deps install step.

### Step 3: Create `tools/consistency_evaluator.py` — standalone CLI evaluator

This file has three responsibilities:
1. **Pipeline runner** — calls Bedrock directly (bypassing handler temperature constraints) for N runs.
2. **Similarity engine** — three metric layers applied to both output layers.
3. **Report printer** — formats and prints results to stdout (and optionally writes JSON).

#### 3a. Imports and constants

Top-level imports must be ONLY stdlib + numpy + jinja2 + sklearn. The `sentence_transformers` and `bert_score` imports must be lazy (inside their respective functions), so the module can be imported without those packages installed (for the test harness's `exec_module` call):

```python
import argparse, boto3, itertools, json, logging, os
from pathlib import Path
import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
```

Do NOT import `sentence_transformers` or `bert_score` at the top level.

Constants:
- `REPO_ROOT = Path(__file__).parent.parent`
- `SCHEMA_DIR = REPO_ROOT / "schemas"`
- `TEMPLATE_DIR = REPO_ROOT / "templates"`
- `DEFAULT_TEMPERATURE = 0.7`
- `DEFAULT_N_RUNS = 5`
- `BERTSCORE_MODEL = "microsoft/deberta-large-mnli"` (faster than xlarge; still recommended)
- `EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"` (biomedical domain; 768-dim, approximately 440 MB — size unverified against current HuggingFace release)

#### 3b. `_build_jinja_env()` — returns a Jinja2 Environment pointing at `templates/`

Mirrors the renderer handler's environment configuration: `autoescape=select_autoescape([])`, `trim_blocks=True`, `lstrip_blocks=True`.

#### 3c. `_load_schema(doc_type: str) -> dict` — loads JSON schema from `schemas/`

#### 3d. `_extract_once(bedrock_runtime, model_id, prompt_text, document_text, schema, doc_type, temperature) -> dict`

Calls `bedrock_runtime.converse()` directly with:
- `inferenceConfig={'maxTokens': 4096, 'temperature': temperature}` — the key override
- `toolConfig` with `toolChoice={'tool': {'name': 'extract_document'}}` (mirrors extractor)
- Returns the `toolUse.input` dict (i.e., `extracted_data`)

This function does NOT use the extractor handler; it calls Bedrock directly so it can set any temperature.

#### 3e. `_render_summary(jinja_env, doc_type, extracted_data: dict) -> str`

Renders the appropriate Jinja2 template using the raw extracted dict. Template variables are unpacked directly from `extracted_data` via `template.render(**extracted_data)`. The parameter is the raw dict as returned by `_extract_once()`, not a renamed or re-validated copy.

#### 3f. `variability_stats(sim_matrix: np.ndarray) -> dict`

Extracts upper-triangle values using `np.triu_indices(n, k=1)`, returns:
- `n_runs`, `n_pairs`, `mean`, `min`, `max`, `std`, `variance`, `cv` (std/mean, or None if mean==0)

All numeric values must be cast to plain Python `float` or `int` before returning (not `np.float64` or `np.int64`). This is a pure function with no AWS or ML dependencies — importable from the test file.

#### 3g. `compute_embedding_similarity(texts: list[str], model) -> dict`

Lazy import at the TOP of this function body:
```python
from sentence_transformers import SentenceTransformer
```

- Calls `model.encode(texts, convert_to_tensor=True)` — returns torch.Tensor
- Calls `model.similarity(embeddings, embeddings).cpu().numpy()` — produces N×N similarity matrix
- Passes to `variability_stats()` and returns result dict with key `"embedding_cosine"`
- Pre-flight check: if any text exceeds 380 words, emit `logging.warning` about potential 512-token truncation

#### 3h. `compute_bertscore_similarity(texts: list[str], scorer) -> dict`

Lazy import at the TOP of this function body:
```python
from bert_score import BERTScorer
```

- Cap inputs FIRST, before computing `n` or entering the combinations loop: `texts = texts[:5]`
- Then `n = len(texts)`
- Builds N×N F1 matrix via `itertools.combinations(range(n), 2)`
- For each pair: `_, _, F1 = scorer.score([texts[i]], [texts[j]])`; stores `F1.item()` (required because `scorer.score()` returns torch.Tensor, not scalar)
- Mirrors the matrix (F1 is approximately symmetric)
- Returns `variability_stats(f1_matrix)` with key `"bertscore_f1"`

#### 3i. `compute_tfidf_similarity(texts: list[str]) -> dict`

- `TfidfVectorizer().fit_transform(texts)` then `sklearn_cosine(tfidf_matrix)`
- Returns `variability_stats(sim_matrix)` with key `"tfidf_cosine"`
- Serves as lightweight baseline with zero model download

#### 3j. `compute_json_field_consistency(extracted_list: list[dict]) -> dict`

Measures structural consistency across N runs at the JSON layer (not semantic):

Field agreement is defined as: `max(Counter(values).values()) / N` — the fraction of runs agreeing with the plurality value (the most common value). With this definition:
- All N runs return same value → score = 1.0
- 2 of 3 runs agree → score = 2/3
- 3 different values in 3 runs → score = 1/3 (not 0)

Values are normalized via `json.dumps` before comparison.

Returns `{"field_agreement": {field_name: float}}`.

#### 3k. `run_evaluation(args) -> dict`

Orchestrates the full evaluation loop:
1. Loads schema and prompt text (from file, not Bedrock Prompt Management — the CLI is standalone)
2. Creates boto3 `bedrock-runtime` client
3. Loads `SentenceTransformer(EMBEDDING_MODEL)` and `BERTScorer(BERTSCORE_MODEL)` (these are the only call sites that trigger the lazy imports)
4. Loops N times: calls `_extract_once()`, `_render_summary()`, collects `extracted_data` and `summary_text` lists
5. Calls all three metric functions on the `summary_text` list (rendered text layer)
6. Calls `compute_json_field_consistency()` on the `extracted_data` list (JSON layer)
7. Assembles and returns a results dict with `"text_layer"` and `"json_layer"` keys

#### 3l. `main()` — argparse CLI entry point

Arguments:
- `--doc-type` — required; one of the five valid doc types
- `--document` — required; path to a document file to process
- `--prompt` — required; path to a plain-text prompt file (the CLI does not call Bedrock Prompt Management)
- `--model-id` — required; Bedrock model ID (must include geo prefix, e.g. `us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- `--n-runs` — optional; default 5; minimum 2
- `--temperature` — optional; default 0.7
- `--output-json` — optional; path to write full JSON results
- `--region` — optional; default `us-east-1`

Prints a human-readable report to stdout. If `--output-json` is given, writes the full results dict to that path.

### Step 4: Create `tests/test_consistency.py` — pytest harness

The test file validates the measurement infrastructure (similarity functions, aggregation, JSON field consistency). It does NOT test Bedrock calls — it uses synthetic text outputs.

#### 4a. Module-level availability check and skip guards

Replace multiple individual `pytest.importorskip` calls with a single module-level availability check to prevent partial-skip inconsistency when only some deps are absent:

```python
import importlib as _importlib
_MISSING_DEPS = [m for m in ("numpy", "sentence_transformers", "bert_score", "sklearn") if _importlib.util.find_spec(m) is None]
pytestmark = pytest.mark.skipif(bool(_MISSING_DEPS), reason=f"Missing ML deps: {_MISSING_DEPS}")
```

This marker is applied uniformly to every test in the file. If any dependency is missing, the entire file is skipped cleanly rather than partially.

#### 4b. Import `variability_stats`, `compute_tfidf_similarity`, `compute_json_field_consistency` from `tools/consistency_evaluator.py`

Use `importlib.util.spec_from_file_location` (the established repo pattern). Wrap `exec_module` in a module-level try/except that converts `ImportError` to a `pytest.skip`:

```python
import importlib.util, sys
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent / 'tools'
_spec = importlib.util.spec_from_file_location('consistency_evaluator', TOOLS_DIR / 'consistency_evaluator.py')
evaluator = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(evaluator)
except ImportError as _e:
    pytest.skip(f"consistency_evaluator import failed: {_e}", allow_module_level=True)

# Register under the bare module name so mock.patch targets resolve correctly
sys.modules['consistency_evaluator'] = evaluator
```

Because `consistency_evaluator.py` uses lazy imports (sentence_transformers and bert_score are NOT at top level), `exec_module()` will NOT trigger those imports. The module-level availability check in 4a is a belt-and-suspenders guard, not the primary import gate.

#### 4c. `TestVariabilityStats` — pure numpy, no ML deps

Tests the `variability_stats()` aggregation function in isolation:

- `test_identical_runs_mean_is_one` — 3×3 matrix with all values 1.0 → mean=1.0, std=0.0
- `test_two_run_single_pair` — 2×2 matrix with off-diagonal 0.8 → n_pairs=1, mean=0.8, cv=0.0
- `test_five_run_known_values` — construct a specific 5×5 matrix with known off-diagonal values; verify mean, min, max, std against hand-computed expected values
- `test_cv_is_none_when_mean_is_zero` — matrix with all off-diagonal=0 → cv=None (not division error)
- `test_diagonal_excluded` — verify that self-similarity (diagonal=1.0) does not inflate mean

#### 4d. `TestTfidfSimilarity` — scikit-learn only, no model download

Tests `compute_tfidf_similarity()` with controlled synthetic texts:

- `test_identical_texts_high_similarity` — N=3 copies of the same text → mean similarity should be very close to 1.0
- `test_completely_different_texts_low_similarity` — texts with zero lexical overlap → mean similarity should be 0.0 (or very close)
- `test_partial_overlap_intermediate_similarity` — texts sharing ~50% of vocabulary → mean in (0, 1)
- `test_returns_expected_keys` — result dict has keys `n_runs`, `n_pairs`, `mean`, `min`, `max`, `std`, `variance`, `cv`
- `test_minimum_two_runs` — called with N=2 → n_pairs=1, result is a dict

#### 4e. `TestEmbeddingSimilarity` — uses `all-MiniLM-L6-v2` (91 MB, fast)

Rather than the ~440 MB PubMedBERT model, the test harness uses `all-MiniLM-L6-v2` for speed. The CLI uses PubMedBERT for accuracy; the test validates the function contract, not the model quality.

- `@pytest.fixture(scope="module")` — loads `SentenceTransformer("all-MiniLM-L6-v2")` once per test session
- `test_identical_texts_high_similarity` — 3 copies of same text → mean > 0.99
- `test_output_dict_keys` — result has all required keys
- `test_return_is_pure_python` — all values in result dict are plain Python `float` or `int`, not `torch.Tensor` or `np.float64` objects (validates the `.cpu().numpy()` and `float()` conversion chain)
- `test_three_texts_with_known_ordering` — high-similarity pair + dissimilar third text → min < mean

#### 4f. `TestBertScoreSimilarity` — uses `distilbert-base-uncased`

NOTE: The `distilbert-base-uncased` model is approximately 260 MB — this figure is unverified against the current HuggingFace release and may differ. This test class should be marked with `@pytest.mark.slow` and excluded from the default CI run unless the runner has enough RAM and disk.

- `@pytest.fixture(scope="module")` — loads `BERTScorer(model_type="distilbert-base-uncased", lang="en")` (lightweight alternative for CI)
- `test_identical_texts_f1_near_one` — same text paired with itself → F1 near 1.0
- `test_f1_item_is_scalar` — validates that `.item()` is called and result is a Python float (not torch.Tensor)
- `test_cap_at_five_texts` — if N>5, only first 5 are compared (latency guard); verify by passing 7 texts and asserting n_pairs == 10 (5 choose 2)
- `test_output_dict_keys` — result has all required keys

#### 4g. `TestJsonFieldConsistency`

Tests `compute_json_field_consistency()` with purely synthetic dicts — no ML or AWS deps:

- `test_all_identical_gives_full_agreement` — 3 identical dicts → all fields score 1.0
- `test_all_different_gives_minimum_agreement` — 3 dicts with a different value for every field in every run → all fields score `pytest.approx(1/3)` (plurality = 1 vote out of 3 runs; per the definition: `max(Counter(values).values()) / N = 1/3`)
- `test_partial_agreement` — 3 dicts where 2/3 agree on one field → that field scores `pytest.approx(2/3)`
- `test_missing_field_in_some_runs` — one run omits a field that others include → agreement is still measurable (absent fields are treated as a distinct value via `json.dumps`)
- `test_nested_dict_serialized_for_comparison` — field containing a list is compared via `json.dumps`

#### 4h. `TestMultiRunOrchestration` — integration test with fully mocked Bedrock

This class tests the `run_evaluation()` function end-to-end but with Bedrock mocked, so it validates the orchestration logic (N calls, result assembly) without ML model loading.

Mock patch targets use the BARE module name `'consistency_evaluator'` (not `'tools.consistency_evaluator'`), because the module was registered in `sys.modules` under the bare name in Step 4b:

```python
mock.patch('consistency_evaluator.compute_embedding_similarity')
mock.patch('consistency_evaluator.compute_bertscore_similarity')
mock.patch('consistency_evaluator.compute_tfidf_similarity')
```

Use `mock.patch` to replace the three metric functions with stubs that return known dicts. Mock `bedrock_runtime.converse()` with a `side_effect` list of N varied responses.

- `test_n_calls_made_to_bedrock` — verifies that `bedrock_runtime.converse()` is called exactly N times
- `test_temperature_override_in_all_calls` — verifies each converse call uses `temperature=0.7` (not 0)
- `test_result_includes_both_layers` — result dict has `"json_layer"` and `"text_layer"` keys
- `test_result_includes_all_metric_keys` — text_layer has `embedding_cosine`, `bertscore_f1`, `tfidf_cosine`

### Step 5: Verify existing test suite is unaffected

Run `pytest tests/ -v` (excluding `test_consistency.py` or with skip guards active) to confirm zero regressions. The new file imports from `tools/consistency_evaluator.py` via `importlib`, so no circular import risk exists.

---

## Risks & Blockers

### Risk 1: Model download size and CI runner disk/memory

- `NeuML/pubmedbert-base-embeddings` is approximately 440 MB (unverified). The CLI uses it; the test file should use `all-MiniLM-L6-v2` (~91 MB) for the embedding tests instead. BERTScore with `distilbert-base-uncased` is the smallest viable option for CI (approximately 260 MB, unverified).
- GitHub Actions free runners have 14 GB disk and ~7 GB RAM. Single model download is fine; downloading both simultaneously risks OOM during CI.
- Mitigation: use `HF_HOME` cache in CI, scope fixtures to `"module"` to load each model once, and mark the BERTScore test class with `@pytest.mark.slow` so it can be excluded with `-m "not slow"`.

### Risk 2: `sentence_transformers.util` always returns torch.Tensor

- `cos_sim`, `pairwise_cos_sim`, and `normalize_embeddings` accept numpy input but return `torch.Tensor`. Any code path that passes their output directly to numpy operations without `.cpu().numpy()` will fail with a `RuntimeError`.
- Mitigation: all similarity matrix construction in `compute_embedding_similarity()` must call `.cpu().numpy()` before passing to `variability_stats()`. The test `test_return_is_pure_python` (Step 4e) catches this regression.

### Risk 3: `bert_score.BERTScorer.score()` returns tensors, not scalars

- The return is three `torch.Tensor` objects. `.item()` must be called on F1 to extract the scalar.
- Mitigation: the code in `compute_bertscore_similarity()` must explicitly call `F1.item()`. The test `test_f1_item_is_scalar` (Step 4f) catches this regression.

### Risk 4: Temperature override — handlers are not modified

- Both classifier and extractor hardcode `temperature=0` in their `inferenceConfig`. The CLI bypasses this by calling `bedrock_runtime.converse()` directly (not calling `handler.lambda_handler()`).
- The extractor handler is re-implemented inline in `_extract_once()`. Any future change to the handler's prompt retrieval or tool schema logic will not automatically propagate to the evaluator.
- Mitigation: document this divergence in a docstring on `_extract_once()`.

### Risk 5: Prompt text sourcing in the CLI

- The production handlers retrieve prompts from Bedrock Prompt Management via `bedrock_agent.get_prompt()`. The CLI is standalone and accepts a local prompt file path instead.
- Mitigation: document in the CLI's `--help` text that the prompt file should match the pinned Bedrock Prompt Management version.

### Risk 6: 512-token limit for BERTScore and PubMedBERT

- Both BERTScore (token-level BERT) and `NeuML/pubmedbert-base-embeddings` have a hard 512-token input limit. Tokens beyond position 512 are silently dropped.
- Mitigation: in `compute_bertscore_similarity()` and `compute_embedding_similarity()`, add a pre-flight check: if any text exceeds 380 words, emit a `logging.warning` that truncation may occur.

### Risk 7: CI torch wheel size

- If `torch` is installed without an explicit index URL, pip may resolve a CUDA wheel on `ubuntu-latest`, adding 2-3 GB of download time. The plan mandates installing CPU-only torch first with `--index-url https://download.pytorch.org/whl/cpu` before sentence-transformers.

### Risk 8: `tools/requirements.txt` must not lose `python-hcl2==8.1.4`

- The existing `tf_arch_diagram.py` tool depends on `python-hcl2==8.1.4`. The Step 1 instruction is to APPEND new deps, not replace the file.

### Risk 9: BERTScore 5-text cap must slice before loop

- The `texts = texts[:5]` slice must occur at the START of `compute_bertscore_similarity()`, before `n = len(texts)` is computed and before the combinations loop begins. Detecting or enforcing the cap after entering the loop is incorrect and must not be implemented.

---

## Testing Strategy

### 1. Pure logic tests (no deps, instant)

```bash
cd /workspace/active_repo
pip install pytest numpy scikit-learn
pytest tests/test_consistency.py::TestVariabilityStats -v
pytest tests/test_consistency.py::TestTfidfSimilarity -v
pytest tests/test_consistency.py::TestJsonFieldConsistency -v
```

These tests have zero ML model dependencies and should complete in under 2 seconds total.

### 2. Embedding similarity tests (requires sentence-transformers + model download)

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "sentence-transformers>=6.1.0"
pytest tests/test_consistency.py::TestEmbeddingSimilarity -v
```

First run downloads `all-MiniLM-L6-v2` (~91 MB). Subsequent runs use the HuggingFace cache.

### 3. BERTScore tests (requires bert-score + model download)

```bash
pip install "bert-score==0.3.13"
pytest tests/test_consistency.py::TestBertScoreSimilarity -v
```

Uses `distilbert-base-uncased` for CI speed. First run downloads approximately 260 MB (unverified).

### 4. Mocked orchestration tests (no model download)

```bash
pytest tests/test_consistency.py::TestMultiRunOrchestration -v
```

All similarity functions are mocked — no model loading, no Bedrock calls.

### 5. Full existing test suite — confirm no regressions

```bash
pytest tests/ -v --ignore=tests/test_consistency.py
```

Then with the new file included:

```bash
pytest tests/ -v
```

The module-level `pytestmark` skipif guard ensures the new test file does not fail if ML deps are absent — tests are skipped gracefully.

### 6. CLI tool smoke test (requires real AWS credentials)

```bash
pip install -r /workspace/active_repo/tools/requirements.txt
python /workspace/active_repo/tools/consistency_evaluator.py \
  --doc-type lab_result \
  --document /path/to/test_lab_report.txt \
  --prompt /workspace/active_repo/prompts/lab_result_prompt.txt \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --n-runs 5 \
  --temperature 0.7 \
  --output-json /tmp/consistency_results.json
```

Expected output: human-readable report with mean/min/std for embedding cosine, BERTScore F1, and TF-IDF cosine; field agreement table for JSON layer.

### 7. Verify temperature override in CLI

After running the CLI, inspect the `--output-json` file. The `metadata.temperature` field should be `0.7`. If calling with `--temperature 0`, the field-level variability should collapse to near-zero (since deterministic Bedrock calls at temperature=0 always return identical output for identical input).

### 8. Verify field_agreement semantics

Run `TestJsonFieldConsistency::test_all_different_gives_minimum_agreement` and confirm the expected value is `pytest.approx(1/3)` (not 0.0). This validates the plurality-fraction definition: `max(Counter(values).values()) / N`.

---

**IMPORTANT — handoff to main agent:** This plan is now written to `/workspace/active_repo/claude-context-plan.md`. The **Plan Reviewer agent MUST be run next** before any implementation begins. No source files should be created or modified until the Reviewer has issued its verdict on this plan.
