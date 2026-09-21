# Plan Review

## Verdict
**APPROVED** — the plan is sound and implementation can begin.

## Flaws Found

_No flaws found._

All seven flaws from the previous review have been correctly resolved. Evidence for each is recorded below.

**Previous flaw 1 — filename authority conflict:** Resolved. The "Canonical Filename Notice" at the top of the plan explicitly states that `gold.html` and `gold.js` supersede the explorer's provisional names `gold-standard.html` and `gold-standard.js`. Every subsequent reference in Steps 7, 8, and 9 consistently uses the canonical names.

**Previous flaw 2 — TF-IDF dropped without rationale or negative test:** Resolved. Step 1 now contains a dedicated "Metric scope — no TF-IDF" paragraph with an explicit rationale. The response contract shows only `{"embedding_cosine", "rouge1"}` as top-level keys. Step 2 includes `test_tfidf_not_in_response` as an explicit negative assertion in `TestResponseStructure`.

**Previous flaw 3 — ThreadPoolExecutor mock fragility:** Resolved. The plan now specifies a named `_bedrock_mock` function using `*args, **kwargs` with a positional fallback (`args[1] if len(args) > 1 else b'{}'`), keyed on `inputText` content rather than call order. The full function body is shown in Step 2.

**Previous flaw 4 — JSZip script placement ambiguity:** Resolved. Step 7 now explicitly states: JSZip CDN script in `<head>`, `config.js` then `gold.js` at the bottom of `<body>`. The rationale (preventing `ReferenceError: JSZip is not defined`) is documented in both Step 7 and Risk item 9. This matches the confirmed placement in `frontend/test.html` (JSZip on line 8 in `<head>`, scripts at the bottom of `<body>`).

**Previous flaw 5 — `test.html` signout-row context:** Resolved. Step 9 now states "The current `signout-row` contains only the sign-out button (no existing nav links)" and provides the exact resulting HTML. This matches the actual `frontend/test.html` confirmed by reading the file (line 50–52: only `<button id="signout-btn" ...>`).

**Previous flaw 6 — validation order unspecified:** Resolved. Step 1 now lists five validation rules in explicit numbered order and states "Validate in this order, returning on the first failure."

**Previous flaw 7 — misleading "consistent with `_variability_stats`" claim:** Resolved. Step 1 now explicitly distinguishes the two: "This divides by `len(scores)` (= N texts). This differs from the pairwise comparator's `_variability_stats` which divides by `n_pairs` (the upper-triangle count, not N). Both use population std — they are not interchangeable and must not be confused."

## Suggested Improvements

**Improvement 1 — `test_invoke_model_called_n_plus_one_times` mock setup is underspecified.**

Step 2 lists this test in `TestMetricCorrectness` but does not show what the `input_text_to_vec` dict should contain or what texts and reference string to use. Because `_bedrock_mock` is keyed on the exact `inputText` string, any mismatch between what the event's `texts` array contains and the dict keys will produce a `KeyError` in `_side_effect` during the test. The implementer must ensure the mock dict covers all N text strings plus the reference string exactly as they appear in the event. A concrete example in the plan would prevent this silent failure mode. Suggested addition to the test description: "Use two text strings and one reference string with distinct values; the `input_text_to_vec` dict must have all three as keys."

**Improvement 2 — `gold.js` section ID for the working UI is not named.**

Step 8 says the plan copies `showAuth` and renames `showTest` to `showGold`. In `test.html`, `showTest` toggles `#test-section`. In `gold.html`, the plan does not state what id the working UI section should have. Step 7 describes the structure of `gold.html` but never assigns an id to the outer section div (it uses `#auth-section` and refers generically to a "test-section" equivalent). If the implementer names it `#test-section` (copying from `test.html`) but the JS function is named `showGold`, the code works but is misleading. If they name it `#gold-section`, they need to update `showGold` accordingly. The plan should state the section id explicitly.

**Improvement 3 — `buildGoldReport` truncation of `referenceText` uses a hard 80-char limit with no ellipsis guard.**

The report template in Step 8 shows: `Reference: <first 80 chars of referenceText>...`. If `referenceText` is shorter than 80 characters, this will append `...` unconditionally and produce `Reference: short text...` even when no truncation occurred. The implementer should conditionally append the ellipsis: only add `...` when `referenceText.length > 80`.

## Revised Steps (if applicable)

No steps require rewriting. All improvements above are minor clarifications that do not change the correctness of any step as written.

## Summary

The plan is accurate, internally consistent, and well-matched to the codebase. All seven flaws from the prior review have been properly addressed with no regressions introduced. The three suggested improvements are low-risk clarifications; none will cause implementation to fail if ignored, though Improvement 1 (mock dict completeness) is the most likely to cause a confusing `KeyError` during test authoring if overlooked. Implementation can begin immediately.
