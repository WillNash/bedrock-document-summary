# Codebase Explorer Findings

## Files examined

- `/workspace/active_repo/research-findings.md` — full document (1156 lines)
- `/workspace/active_repo/tests/conftest.py`
- `/workspace/active_repo/tests/test_classifier.py`
- `/workspace/active_repo/tests/test_extractor.py`
- `/workspace/active_repo/tests/test_validator.py`
- `/workspace/active_repo/tests/test_renderer.py`
- `/workspace/active_repo/tests/test_renderer_handler.py`
- `/workspace/active_repo/tests/test_schemas.py`
- `/workspace/active_repo/tests/test_api_summary.py`
- `/workspace/active_repo/tests/test_api_status.py`
- `/workspace/active_repo/lambda/classifier/handler.py`
- `/workspace/active_repo/lambda/extractor/handler.py`
- `/workspace/active_repo/lambda/validator/handler.py`
- `/workspace/active_repo/lambda/renderer/handler.py`
- `/workspace/active_repo/lambda/pipeline_starter/handler.py`
- `/workspace/active_repo/schemas/lab_result_schema.json`
- `/workspace/active_repo/tools/tf_arch_diagram.py`
- `/workspace/active_repo/summarizer-options.md`

---

## Section 2 of research-findings.md: Semantic Similarity Metrics (lines 139–262)

Three approaches are documented:

**BERTScore** — token-level cosine similarity via contextual embeddings.
- Precision: (1/m) * sum_i max_j cos(c_i, r_j)
- Recall: (1/n) * sum_j max_i cos(c_i, r_j)
- F1: 2*P*R/(P+R)
- For N runs: compute all N*(N-1)/2 pairwise F1 scores, report mean/min/std.
- Recommended clinical model: `emilyalsentzer/Bio_ClinicalBERT` or `microsoft/deberta-xlarge-mnli`.
- Implementation uses `from evaluate import load; bertscore = load("bertscore")`.
- Hard limit: 512 tokens per text — long docs need chunking. Never mix rescaled and unrescaled scores.

**Sentence Embeddings + Cosine Similarity** — full-text dense vector encoding.
- `cosine_similarity(A, B) = (A . B) / (||A|| * ||B||)`
- Build N×N similarity matrix; report mean/std/min of off-diagonal entries.
- Threshold: >0.90 = high consistency; <0.75 = concerning.
- Recommended models: `all-MiniLM-L6-v2` (fast, 384-dim), `all-mpnet-base-v2` (higher quality, 768-dim), `pritamdeka/S-PubMedBert-MS-MARCO` (biomedical domain).
- Implementation: `from sentence_transformers import SentenceTransformer; embeddings = model.encode(outputs, normalize_embeddings=True); sim_matrix = embeddings @ embeddings.T`

**STS Cross-Encoders** — `CrossEncoder('cross-encoder/stsb-roberta-large')`. Attends jointly to both texts — more accurate than bi-encoders but higher compute. Outputs 0–1 score per pair.

**Key finding for medical text:** Surface metrics (ROUGE/BLEU) are inadequate as sole metrics — "no fracture noted" vs "fracture noted" scores high overlap but opposite meaning. BERTScore correctly gives low similarity when polarity differs.

**Reference implementation:** The file contains a complete `MedicalSummarizationConsistencyEvaluator` class (lines 961–1015) that:
- Computes pairwise ROUGE-L across all N*(N-1)/2 pairs
- Computes sentence embedding cosine similarity matrix (off-diagonal)
- Computes BERTScore (capped at first 5 outputs for latency)
- Returns dict with mean/std/min for each metric layer

---

## Existing multi-run test infrastructure: none

There is **zero existing infrastructure** for multi-run or N-run comparisons. No fixture, helper, or test invokes any handler more than once. The `conftest.py` only sets dummy AWS credentials. All test files follow the same pattern:
1. Import handler via `importlib.util.spec_from_file_location`
2. Define `MOCK_ENV` dict with required env vars
3. Use `@pytest.fixture(autouse=True)` with `monkeypatch` for env vars
4. Use `mock.patch.object(handler, 'bedrock_runtime')` etc. to mock AWS clients
5. Define factory functions like `make_converse_response(label)`, `make_s3_response(text)`, `make_tool_use_response(tool_input)`
6. Organise tests into classes by concern

---

## Lambda handler architecture

### Full pipeline sequence
`S3 upload → pipeline_starter → Step Functions → classifier → extractor → validator → renderer`

### classifier (`lambda/classifier/handler.py`)
- Input event: `{job_id, bucket, key}`
- Reads document from S3, calls `bedrock-agent.get_prompt()` then `bedrock-runtime.converse()`
- Model: `BEDROCK_CLASSIFIER_MODEL_ID` (Claude Haiku), **`temperature=0`**, `maxTokens=20`
- Returns: `{job_id, bucket, key, doc_type, usage_stats.classifier}`
- `doc_type` must be one of: `lab_result, doctors_notes, injury_doc, visit_assessment, psych_eval`

### extractor (`lambda/extractor/handler.py`)
- Input event: adds `doc_type` to classifier output
- Forces `toolChoice: {tool: {name: "extract_document"}}` — response always contains toolUse block
- Loads JSON schema from `schemas/{doc_type}_schema.json`
- Model: `BEDROCK_MODEL_ID` (Claude Sonnet), **`temperature=0`**, `maxTokens=4096`
- Returns: adds `extracted_data` (the toolUse input dict) + `usage_stats.extractor`

### validator (`lambda/validator/handler.py`)
- Runs `jsonschema.validate(instance=extracted_data, schema=schema)` — raises on failure
- Returns: renames `extracted_data` to `validated_data`, passes everything else through
- No Bedrock calls — pure schema validation

### renderer (`lambda/renderer/handler.py`)
- Renders `validated_data` via Jinja2 template (`templates/{doc_type}.j2`)
- Writes `summaries/{job_id}/summary.txt` and `summaries/{job_id}/usage.json` to S3
- Updates DynamoDB `jobs` table: `status=COMPLETED, doc_type, completed_at`
- Returns: `{job_id, summary_key}`

---

## Key design constraints for the new feature

1. **Temperature=0 everywhere.** Both classifier and extractor hardcode `temperature=0` in `inferenceConfig`. To get meaningful variance signal across N runs, the new feature must override temperature (research recommends 0.7). Options: (a) parameterise the handlers or (b) call `bedrock_runtime.converse()` directly, bypassing the handler's hardcoded value. Option (b) is lower-risk (no handler modification).

2. **AWS clients are module-level singletons.** A multi-run harness using real Bedrock calls cannot use `mock.patch.object` — it needs real credentials. A test-oriented harness can use mock responses with varied `side_effect` lists.

3. **Two measurable output layers:**
   - Structured JSON: `extracted_data` / `validated_data` dict from extractor/validator — field-level consistency
   - Rendered text: summary string from renderer — semantic similarity via embeddings or BERTScore

4. **Recommended implementation location:**
   - `tests/test_consistency.py` — pytest-based harness using mock varied outputs (tests the measurement infrastructure)
   - `tools/consistency_evaluator.py` — standalone CLI tool making real Bedrock calls (tests actual pipeline variability)
   - New dependencies (`sentence-transformers`, `evaluate`, `rouge-score`, `bert-score`) belong in `tools/requirements.txt`
