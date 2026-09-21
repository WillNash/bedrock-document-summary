# Plan Review

## Verdict
**APPROVED** — all 9 flaws from the previous review have been resolved. One residual minor note is documented below, but it is not a blocker.

---

## Flaws Found

_No blocking flaws found._ The previous 9 flaws are addressed as follows:

**Flaw 1 — tools/requirements.txt python-hcl2 preservation:** RESOLVED. Step 1 now explicitly states "Do NOT overwrite it. The file currently contains only `python-hcl2==8.1.4`, which must remain." and instructs APPEND. The actual file at `/workspace/active_repo/tools/requirements.txt` contains exactly `python-hcl2==8.1.4` on line 1 — the constraint is accurate and the instruction is unambiguous.

**Flaw 2 — CI torch resolution pulling CUDA wheel:** RESOLVED. Step 2 now mandates two separate YAML steps, with a dedicated "Install CPU-only torch (prevents 2-3 GB CUDA wheel download)" step using `--index-url https://download.pytorch.org/whl/cpu` that must come first, before sentence-transformers is installed. The plan explicitly documents the failure mode and why ordering matters.

**Flaw 3 — module-level exec_module triggering heavy imports:** RESOLVED. Step 3a now explicitly restricts top-level imports to stdlib + numpy + jinja2 + sklearn only. `sentence_transformers` and `bert_score` are moved to lazy imports inside their respective function bodies (`compute_embedding_similarity` and `compute_bertscore_similarity`). Step 4b confirms: "Because `consistency_evaluator.py` uses lazy imports (sentence_transformers and bert_score are NOT at top level), `exec_module()` will NOT trigger those imports."

**Flaw 4 — _render_summary variable naming vs validated_data:** RESOLVED (the plan correctly notes this in Step 3e). The plan explicitly states that `template.render(**extracted_data)` works identically to `template.render(**validated_data)` because the template variables are the dict keys, not the variable names. The explanation is clear enough to prevent implementation confusion.

**Flaw 5 — mock.patch target using wrong module path:** RESOLVED. Step 4b now explicitly registers the module under the bare name: `sys.modules['consistency_evaluator'] = evaluator`. Step 4h explicitly uses `mock.patch('consistency_evaluator.compute_embedding_similarity')` (bare name, not `tools.consistency_evaluator`) and explains the reason: "Mock patch targets use the BARE module name `'consistency_evaluator'` (not `'tools.consistency_evaluator'`), because the module was registered in `sys.modules` under the bare name in Step 4b."

**Flaw 6 — BERTScore cap logic ambiguity (slice before loop):** RESOLVED. Step 3h now explicitly states: "Cap inputs FIRST, before computing `n` or entering the combinations loop: `texts = texts[:5]`. Then `n = len(texts)`." The ordering is unambiguous. The test `test_cap_at_five_texts` in Step 4f validates this by passing 7 texts and asserting `n_pairs == 10`.

**Flaw 7 — test_all_different field agreement expected value was wrong/undefined:** RESOLVED. Step 3j now precisely defines the field agreement formula (`max(Counter(values).values()) / N`), documents the three example cases (1.0 for unanimous, 2/3 for two-of-three, 1/3 for all-different), and Step 4g now names the test `test_all_different_gives_minimum_agreement` with expected value `pytest.approx(1/3)`.

**Flaw 8 — distilbert-base-uncased size unverified:** RESOLVED. Step 4f now explicitly labels the "~260 MB" figure as unverified: "approximately 260 MB — this figure is unverified against the current HuggingFace release and may differ." The Risks section (Risk 1) also carries the same unverified qualifier. This is appropriate epistemic honesty and does not require verification to proceed.

**Flaw 9 — partial-skip inconsistency from multiple importorskip calls:** RESOLVED. Step 4a now replaces individual `pytest.importorskip` calls with a single module-level `pytestmark` using `pytest.mark.skipif` driven by a `_MISSING_DEPS` list check. The plan states: "This marker is applied uniformly to every test in the file. If any dependency is missing, the entire file is skipped cleanly rather than partially."

---

## Residual Minor Note (Non-blocking)

**Note — exec_module try/except ordering relative to pytestmark:** Step 4a sets `pytestmark` using `_MISSING_DEPS` (a static `find_spec` check), then Step 4b wraps `exec_module` in a `try/except ImportError` that calls `pytest.skip(allow_module_level=True)`. These two mechanisms are complementary and both correct. However, there is a subtle sequencing question: if `_MISSING_DEPS` is empty (all packages found by `find_spec`) but `exec_module` still raises `ImportError` for some other reason (e.g., a broken install), the `pytestmark` will not fire but the `try/except` in 4b will. This is the correct fallback behaviour. The plan handles both paths — the belt-and-suspenders framing in Step 4b is accurate. No change needed; this is noted for implementer awareness only.

**Note — HuggingFace model cache key lacks version hash:** Step 2 defines the cache key as `hf-models-all-minilm-distilbert` (a static string). If either model is updated on HuggingFace, the cache will serve the stale version indefinitely. This is acceptable for a CI test harness (model quality consistency is desirable), but implementers should be aware the cache will not automatically invalidate on model updates. No blocker.

---

## Suggested Improvements

- **Improvement 1 — Document the `--validate` gap in the CLI's --help text:** The plan correctly acknowledges in Risk 4 that `_extract_once()` diverges from the handler (no schema validation). Step 3l lists the CLI arguments but does not mention a note in `--help` about this. Add a note in the `main()` docstring or argparse description stating that extracted data is not schema-validated by default — matching the Improvement 8 suggestion from the previous review, which this plan did not address. This is low priority but worth including for operational correctness.

- **Improvement 2 — Consider a `--slow` CI marker exclusion in the default pytest run:** The plan marks `TestBertScoreSimilarity` with `@pytest.mark.slow` but the existing `ci.yml` runs `pytest tests/ -v` with no marker filter. After the new step is added, the `Run tests` step will execute all tests including the slow BERTScore class. If disk or RAM is tight on the runner, this may cause OOM. Suggest updating the `Run tests` line to `pytest tests/ -v -m "not slow"` and running the slow tests in a separate optional job, or explicitly noting in the plan that the default CI run must be updated to add `-m "not slow"`.

---

## Revised Steps (if applicable)

Only one step requires a concrete correction — the existing `Run tests` step in ci.yml should exclude slow tests by default. The plan does not address this gap.

**Revised Step 2 addition — Update "Run tests" step in ci.yml**

The existing `Run tests` step runs:
```
pytest tests/ -v
```

This must be changed to:
```
pytest tests/ -v -m "not slow"
```

Otherwise `TestBertScoreSimilarity` (marked `@pytest.mark.slow`) will be executed on every push, loading the distilbert-base-uncased model (~260 MB) and running BERTScore inference against the CI runner's RAM and disk budget on every CI run. The plan introduces the `@pytest.mark.slow` marker but does not carry through the necessary change to the `Run tests` invocation.

The plan should also add a `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` block registering the `slow` marker to avoid the "PytestUnknownMarkWarning" that pytest emits for unregistered custom markers.

---

## Summary

The revised plan correctly resolves all 9 flaws from the previous review. The architecture is sound, the lazy-import pattern cleanly separates the CLI's ML dependencies from the test harness's import-time surface, and the mock.patch registration strategy is now consistent end-to-end. The one remaining gap — that `@pytest.mark.slow` is introduced but the `Run tests` CI step is not updated to exclude it — should be addressed before implementation completes, but it is not a blocker to beginning implementation.
