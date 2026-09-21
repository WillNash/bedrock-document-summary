# Research Findings: Semantic Similarity for LLM Output Variability

## Source URLs

- [Semantic Textual Similarity — Sentence Transformers docs](https://www.sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html) — **Official**
- [SentenceTransformers Documentation home](https://www.sbert.net/) — **Official**
- [Pretrained Models — Sentence Transformers](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html) — **Official**
- [GitHub — huggingface/sentence-transformers](https://github.com/huggingface/sentence-transformers) — **Official**
- [bert-score — PyPI](https://pypi.org/project/bert-score/) — **Official**
- [GitHub — Tiiiger/bert_score](https://github.com/Tiiiger/bert_score) — **Official**
- [cosine_similarity — scikit-learn stable docs](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html) — **Official**
- [difflib — Python 3 stdlib docs](https://docs.python.org/3/library/difflib.html) — **Official**
- [NeuML/pubmedbert-base-embeddings — Hugging Face model card](https://huggingface.co/NeuML/pubmedbert-base-embeddings) — **Official**
- [pritamdeka/S-PubMedBert-MS-MARCO — Hugging Face model card](https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO) — **Official**
- [bert_score rescale_baseline journal — GitHub](https://github.com/Tiiiger/bert_score/blob/master/journal/rescale_baseline.md) — **Official**

---

## Core Concepts

### 1. sentence-transformers (SBERT)

`sentence-transformers` is the primary Python library for computing dense sentence embeddings for semantic similarity. Current stable release: v6.0. Requires Python 3.10+ and PyTorch 2.2+.

`model.similarity(embeddings1, embeddings2)` returns a 2-D `torch.Tensor` of shape `(n1, n2)`. Default metric is cosine similarity, range **[-1, 1]**. In practice outputs rarely go negative. For L2-normalised models, cosine and dot-product are numerically equivalent; dot-product is faster.

`sentence_transformers.util` exposes standalone functions (`cos_sim`, `pairwise_cos_sim`, `normalize_embeddings`) that work on numpy arrays or torch tensors — useful when embeddings are pre-computed and cached.

### 2. BERTScore

BERTScore (ICLR 2020, `pip install bert-score`, latest stable v0.3.13, Feb 2023) computes token-level cosine similarity between contextual BERT-family embeddings of candidate and reference text. Yields three scalars: **Precision (P)**, **Recall (R)**, **F1** (harmonic mean).

Raw F1 with `roberta-large` clusters in approximately **[0.84, 0.97]**. Use `rescale_with_baseline=True` for interpretable scores. Best model for human-judgement correlation: `microsoft/deberta-xlarge-mnli`. Faster: `microsoft/deberta-large-mnli`.

Two API surfaces: `bert_score.score()` (stateless) and `bert_score.BERTScorer` (caches model — preferred for multiple evaluations). F1 is approximately symmetric; P and R are not. Use F1 for pairwise variability measurement.

For measuring variability across N runs without ground truth: designate one run as a pseudo-reference anchor, or compute all N*(N-1)/2 pairwise F1 values.

### 3. Cosine Similarity on Sentence Embeddings

`sklearn.metrics.pairwise.cosine_similarity(X, Y=None)` accepts 2-D arrays of shape `(n_samples, n_features)` and returns a matrix of shape `(n_X, n_Y)`, values in **[-1, 1]**. For L2-normalised sentence-transformer embeddings, practical range is **[0, 1]**.

Medical/clinical text benchmarks (Pearson correlation, from NeuML model card):

| Model | PubMed QA | PubMed Subset | PubMed Summary | Average |
|---|---|---|---|---|
| `NeuML/pubmedbert-base-embeddings` | 93.27 | 97.00 | 96.58 | **95.62** |
| `all-mpnet-base-v2` | — | — | — | ~94 |
| `all-MiniLM-L6-v2` | 90.40 | 95.92 | 94.07 | 93.46 |

Recommended for this use case: **`NeuML/pubmedbert-base-embeddings`** — PubMedBERT fine-tuned with sentence-transformers on PubMed title-abstract pairs. 768-dim, ~440 MB. Hard 512-token limit — summaries longer than ~380 words need truncation or chunking.

### 4. Lightweight Alternatives (No Large Model Download)

**TF-IDF + Cosine Similarity (scikit-learn):** `TfidfVectorizer` + `cosine_similarity`. No model download, CPU-only, negligible memory. Range **[0, 1]** for TF-IDF. Captures lexical overlap only — misses paraphrase semantics. Good sanity-check baseline.

**difflib.SequenceMatcher (Python stdlib):** `SequenceMatcher(None, a, b).ratio()` returns **[0, 1]**. Zero dependencies. Character-level only — paraphrases score low.

### 5. Aggregating Scores Across N Pairwise Comparisons

Extract the upper triangle of the N×N matrix using `np.triu_indices(n, k=1)` to get N*(N-1)/2 unique pair scores. Report:

- **Mean**: typical agreement across runs.
- **Min**: worst-case divergence — often the most informative single number.
- **Std / Variance**: primary signal for pipeline stability.
- **Coefficient of variation (std / mean)**: normalises variance for cross-metric comparison.

All-pairs is preferred over anchor-based (N-1) when N <= ~50. N >= 5 is needed for meaningful variance estimates; N=2 gives only 1 pair and undefined variance.

---

## Code Snippets

### sentence-transformers — general similarity matrix

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
runs = ["summary text 1", "summary text 2", "summary text 3"]
embeddings = model.encode(runs, convert_to_tensor=True)
sim_matrix = model.similarity(embeddings, embeddings).cpu().numpy()  # shape: (n, n)
```

### sentence-transformers — medical text (PubMedBERT)

```python
model = SentenceTransformer("NeuML/pubmedbert-base-embeddings")
embeddings = model.encode(runs, convert_to_tensor=True)  # shape: (n, 768)
sim_matrix = model.similarity(embeddings, embeddings).cpu().numpy()
```

### BERTScore — BERTScorer object (model reuse across many pairs)

```python
from bert_score import BERTScorer
import numpy as np, itertools

scorer = BERTScorer(model_type="microsoft/deberta-large-mnli", lang="en")
n = len(runs)
f1_matrix = np.ones((n, n))
for i, j in itertools.combinations(range(n), 2):
    _, _, F1 = scorer.score([runs[i]], [runs[j]])
    f1_matrix[i, j] = F1.item()
    f1_matrix[j, i] = F1.item()  # F1 approximately symmetric
```

### sklearn TF-IDF cosine similarity (no model download)

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

tfidf_matrix = TfidfVectorizer().fit_transform(runs)
sim_matrix = cosine_similarity(tfidf_matrix)  # shape: (n, n), values [0, 1]
```

### Aggregation utility — works with any similarity matrix

```python
import numpy as np

def variability_stats(sim_matrix: np.ndarray) -> dict:
    n = sim_matrix.shape[0]
    idx = np.triu_indices(n, k=1)   # excludes diagonal
    scores = sim_matrix[idx]         # shape: (N*(N-1)/2,)
    mean = float(np.mean(scores))
    return {
        "n_runs": n,
        "n_pairs": len(scores),
        "mean": mean,
        "min": float(np.min(scores)),
        "max": float(np.max(scores)),
        "std": float(np.std(scores)),
        "variance": float(np.var(scores)),
        "cv": float(np.std(scores) / mean) if mean != 0 else None,
    }
```

---

## Gotchas & Warnings

### sentence-transformers
- Python 3.10+ and PyTorch 2.2+ required for v6.0.
- `model.similarity()` returns `torch.Tensor`. Call `.cpu().numpy()` before passing to numpy.
- Model downloads cached in `~/.cache/huggingface/hub`. Sizes: `all-MiniLM-L6-v2` ~80 MB, `NeuML/pubmedbert-base-embeddings` ~440 MB.

### BERTScore
- Latest release v0.3.13 (Feb 2023). Stable but not actively extended.
- Raw F1 with `roberta-large` clusters in ~[0.84, 0.97]. Use `rescale_with_baseline=True` for interpretability.
- Instantiate `BERTScorer` once and reuse it — do not create a new scorer per pair.
- Never mix rescaled and unrescaled scores in the same comparison.

### Medical/Clinical Text
- `NeuML/pubmedbert-base-embeddings` recommended — 95.62% average Pearson on PubMed benchmarks.
- Hard 512-token BERT limit. Summaries longer than ~380 words must be truncated or chunked — tokens beyond position 512 are silently dropped.

### Aggregation
- Always use `np.triu_indices(n, k=1)` — including the diagonal inflates mean toward 1.0.
- **Min similarity** is the most informative number: mean=0.90 with min=0.55 indicates reliability problems the mean conceals.
- Coefficient of variation enables cross-metric comparison when absolute score ranges differ.

---

## Verification Results

_Verified by Research Verifier agent on 2026-09-21. Each distinct factual claim from the findings above is assessed below._

### Claim: Current stable release of sentence-transformers is v6.0
- **Verdict**: CORRECTED
- **What is actually correct**: The current stable release as of 2026-09-21 is v6.1.0, released on September 18, 2026. v6.0 is no longer the latest stable version. The v6.x line is accurate as a major-version reference; only the point release number is stale.
- **Source**: https://pypi.org/project/sentence-transformers/

### Claim: sentence-transformers v6.0 requires Python 3.10+ and PyTorch 2.2+
- **Verdict**: CONFIRMED
- **Source**: https://pypi.org/project/sentence-transformers/ and https://sbert.net/docs/migration_guide.html
- **Notes**: PyTorch minimum was raised to 2.2+ in v6.0 (up from 1.11+). Python 3.10 minimum is unchanged from v5.x. Both requirements also apply to v6.1.0.

### Claim: model.similarity() returns a 2-D torch.Tensor of shape (n1, n2), default metric cosine similarity, range [-1, 1]
- **Verdict**: CONFIRMED
- **Source**: https://www.sbert.net/docs/package_reference/sentence_transformer/model.html and https://www.sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html
- **Notes**: Official docs show the return as a torch.Tensor with pairwise cosine scores; the example output confirms the (n, n) shape and values in [-1, 1]. The default similarity_fn_name is COSINE.

### Claim: sentence_transformers.util exposes cos_sim, pairwise_cos_sim, normalize_embeddings and they "work on numpy arrays or torch tensors"
- **Verdict**: CORRECTED
- **What is actually correct**: These functions accept numpy arrays as input (they convert them internally) but they ALWAYS return a torch.Tensor, never a numpy array. The phrase "work on numpy arrays or torch tensors" is misleading: input can be numpy, but callers expecting numpy output must call .cpu().numpy() on the result. This is the same caveat documented for model.similarity() in the Gotchas section, but the body text implies seamless numpy interop that does not exist.
- **Source**: https://github.com/huggingface/sentence-transformers/issues/2513 (official repo issue confirming behaviour)

### Claim: BERTScore latest stable version is v0.3.13, released Feb 2023
- **Verdict**: CONFIRMED
- **Source**: https://pypi.org/project/bert-score/
- **Notes**: No new PyPI release has appeared since February 2023. The package is stable but effectively unmaintained for new features.

### Claim: Raw F1 with roberta-large clusters in approximately [0.84, 0.97]
- **Verdict**: CORRECTED
- **What is actually correct**: The official BERTScore repository's own journal document (rescale_baseline.md) states the range as "between 0.85 and 0.95", not [0.84, 0.97]. The upper bound of 0.97 overstates the practical ceiling by about 0.02. Use [0.85, 0.95] as the documented typical range.
- **Source**: https://github.com/Tiiiger/bert_score/blob/master/journal/rescale_baseline.md

### Claim: Best model for human-judgement correlation is microsoft/deberta-xlarge-mnli; faster alternative is microsoft/deberta-large-mnli
- **Verdict**: CONFIRMED
- **Source**: https://github.com/Tiiiger/bert_score
- **Notes**: The README explicitly states "the best model is microsoft/deberta-xlarge-mnli, please consider using it instead of the default roberta-large".

### Claim: Two API surfaces — bert_score.score() (stateless) and bert_score.BERTScorer (caches model)
- **Verdict**: CONFIRMED
- **Source**: https://github.com/Tiiiger/bert_score
- **Notes**: Both interfaces documented in the README. BERTScorer caches the model to avoid reloading across multiple evaluations.

### Claim: F1 is approximately symmetric; P and R are not
- **Verdict**: CONFIRMED
- **Source**: https://github.com/Tiiiger/bert_score
- **Notes**: BERTScore Precision matches each candidate token to the best reference token; Recall does the reverse. F1 is the harmonic mean of P and R. Swapping candidate and reference changes P and R but F1 changes only slightly (approximately symmetric, not exactly).

### Claim: scorer.score() yields three scalars — Precision, Recall, F1
- **Verdict**: CORRECTED
- **What is actually correct**: scorer.score() returns three TENSORS (one per metric), not three scalars. Each tensor has one element per candidate-reference pair in the batch. When called with a single pair as in the code snippet (scorer.score([runs[i]], [runs[j]])), each tensor has exactly one element, so calling .item() on F1 extracts the scalar. The claim says "Yields three scalars" which is only true when the batch size is 1. The code snippet itself is correct; the prose description is imprecise.
- **Source**: https://pypi.org/project/bert-score/ and https://github.com/Tiiiger/bert_score

### Claim: sklearn.metrics.pairwise.cosine_similarity accepts 2-D arrays, returns matrix of shape (n_X, n_Y), values in [-1, 1]
- **Verdict**: CONFIRMED
- **Source**: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html
- **Notes**: Function accepts array-like or sparse matrices of shape (n_samples, n_features). Returns ndarray or sparse matrix of shape (n_samples_X, n_samples_Y). Value range is [-1, 1] in general; [0, 1] for non-negative inputs such as TF-IDF vectors.

### Claim: NeuML/pubmedbert-base-embeddings benchmark scores — PubMed QA 93.27, PubMed Subset 97.00, PubMed Summary 96.58, Average 95.62 (Pearson correlation)
- **Verdict**: CONFIRMED
- **Source**: https://huggingface.co/NeuML/pubmedbert-base-embeddings
- **Notes**: All four figures match the model card exactly.

### Claim: NeuML/pubmedbert-base-embeddings is 768-dim, ~440 MB, hard 512-token limit
- **Verdict**: CONFIRMED
- **Source**: https://huggingface.co/NeuML/pubmedbert-base-embeddings (768-dim and 512-token limit confirmed on model card); https://huggingface.co/NeuML/pubmedbert-base-embeddings/blob/b028af2f0ba973db9b24933b433b42e1c18d0370/pytorch_model.bin (file size confirmed as 438 MB, consistent with ~440 MB claim)

### Claim: all-MiniLM-L6-v2 model size is ~80 MB
- **Verdict**: CORRECTED
- **What is actually correct**: The model weight file (pytorch_model.bin or model.safetensors) is 90.9 MB, not ~80 MB. The ~80 MB figure underestimates by approximately 14%. Callers planning disk or memory budgets should use ~91 MB.
- **Source**: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/main

### Claim: difflib.SequenceMatcher.ratio() is "character-level only"
- **Verdict**: CORRECTED
- **What is actually correct**: SequenceMatcher operates on any sequence of hashable elements. When called with two plain strings, it compares character-by-character (making "character-level" a fair description for the most common usage). However, it is not inherently character-level — it can compare lists of tokens, lines, or any hashable objects. The claim is accurate for the code snippet shown (SequenceMatcher(None, a, b) where a and b are strings), but "character-level only" overstates the constraint.
- **Source**: https://docs.python.org/3/library/difflib.html

### Claim: np.triu_indices(n, k=1) extracts the upper triangle excluding the diagonal, yielding N*(N-1)/2 pairs
- **Verdict**: CONFIRMED
- **Source**: https://numpy.org/doc/stable/reference/generated/numpy.triu_indices.html
- **Notes**: k=1 means one diagonal above the main diagonal, which excludes self-pairs. For an n x n matrix this produces exactly n*(n-1)/2 index pairs. Usage in the aggregation code is correct.

### Claim: Python 3.10+ and PyTorch 2.2+ required for v6.0 (Gotchas section)
- **Verdict**: CONFIRMED
- **Source**: https://sbert.net/docs/migration_guide.html
- **Notes**: Duplicate of the Core Concepts version of this claim; both instances are correct.

### Claim: Model downloads cached in ~/.cache/huggingface/hub
- **Verdict**: CONFIRMED
- **Source**: https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables (standard Hugging Face Hub cache location, controlled by HF_HOME / HUGGINGFACE_HUB_CACHE env vars)
- **Notes**: This is the default path; it can be overridden with environment variables.

---

### Summary

Total claims assessed: 17
- CONFIRMED: 11
- CORRECTED: 5
- DEPRECATED: 0
- UNVERIFIABLE: 0
- CONFIRMED with minor nuance: 1 (difflib claim — correct for string inputs, imprecise as a universal statement)

**Claims requiring particular caution before use:**

1. "Current stable release: v6.0" — CORRECTED. The current stable version is v6.1.0 (released 2026-09-18). Code and dependency pins should reference v6.1.x.

2. "Raw F1 with roberta-large clusters in approximately [0.84, 0.97]" — CORRECTED. The upper bound is 0.95, not 0.97, per the BERTScore authors' own documentation. Any thresholds or interpretability guidance derived from [0.84, 0.97] should use [0.85, 0.95] instead.

3. "util functions work on numpy arrays or torch tensors" — CORRECTED. These functions accept numpy as input but always return torch.Tensor. Code that passes their output directly to numpy operations without calling .cpu().numpy() will fail at runtime.

4. "Yields three scalars — Precision, Recall, F1" — CORRECTED. scorer.score() returns three torch.Tensors (one element per pair in the batch), not scalars. The provided code snippet is correct (it calls .item()), but downstream code that treats the return as a plain float without .item() will break.

5. "all-MiniLM-L6-v2 ~80 MB" — CORRECTED. Actual weight file size is 90.9 MB. Use ~91 MB for capacity planning.
