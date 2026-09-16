# Research Findings

## Source URLs
- [Easy Guide to ROUGE, BLEU, and METEOR Metrics](https://medium.com/@diwakarkumar_18755/easy-guide-to-rouge-bleu-and-meteor-metrics-to-evaluate-llm-outputs-7afa5a3e1ca3)
- [LLM Evaluation Metrics - Manish Poddar](https://manish-poddar.medium.com/llm-evaluation-metrics-8ac3bd728439)
- [Consistency Matters: Explore LLMs Consistency From a Black-Box Perspective](https://arxiv.org/pdf/2402.17411)
- [BERTScore For LLM Evaluation - Comet](https://www.comet.com/site/blog/bertscore-for-llm-evaluation/)
- [BERTScore: A Contextual Metric for LLM Evaluation - Analytics Vidhya](https://www.analyticsvidhya.com/blog/2025/04/bertscore-a-contextual-metric-for-llm-evaluation/)
- [Reliability without Validity: LLM-as-a-Judge Across Agreement, Consistency, and Bias](https://arxiv.org/html/2606.19544v1)
- [A Systematic Study of Position Bias in LLM-as-a-Judge](https://aclanthology.org/2025.ijcnlp-long.18.pdf)
- [Judging the Judges: Position Bias in LLM-as-a-Judge (arXiv)](https://arxiv.org/abs/2406.07791)
- [Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge](https://arxiv.org/pdf/2410.02736)
- [Estimating the Self-Consistency of LLMs](https://arxiv.org/html/2509.19489)
- [Self-Consistency Evaluation Metric - FutureAGI](https://futureagi.com/glossary/self-consistency-evaluation-metric/)
- [STED and Consistency Scoring: Evaluating LLM Structured Output Reliability](https://arxiv.org/html/2512.23712)
- [The Structured Output Benchmark](https://arxiv.org/html/2604.25359v1)
- [ReEvalMed: Rethinking Medical Report Evaluation](https://arxiv.org/html/2510.00280v1)
- [RadEval: A framework for radiology text evaluation](https://arxiv.org/pdf/2509.18030)
- [GREEN: Generative Radiology Report Evaluation and Error Notation](https://arxiv.org/pdf/2405.03595)
- [GREEN - ACL Anthology](https://aclanthology.org/2024.findings-emnlp.21/)
- [RadGraph: Extracting Clinical Entities and Relations](https://arxiv.org/abs/2106.14463)
- [When Large Language Models Fail in Healthcare: Evaluating Sensitivity to Prompt Variations](https://arxiv.org/pdf/2606.07237)
- [Benchmarking Prompt Sensitivity in LLMs](https://ls3lab.com/promptengineering___ecir_25-3/)
- [Prompt Stability in Code LLMs: Measuring Sensitivity](https://arxiv.org/html/2509.13680v1)
- [DeepEval Metrics Introduction](https://deepeval.com/docs/metrics-introduction)
- [Promptfoo Assertions and Metrics](https://www.promptfoo.dev/docs/configuration/expected-outputs/)
- [RAGAS Available Metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
- [Semantic Textual Similarity - Sentence Transformers](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html)
- [QuickUMLS: fast unsupervised medical concept extraction](https://ir.cs.georgetown.edu/downloads/quickumls.pdf)
- [Clinical concept recognition evaluation - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9880223/)
- [Inter-Annotator Agreement - Cohen's Kappa](https://surge-ai.medium.com/inter-annotator-agreement-an-introduction-to-cohens-kappa-statistic-dcc15ffa5ac4)
- [Giskard LLM Evaluation Platform](https://www.giskard.ai/products/llm-evaluation)
- [Choosing the Right LLM Evaluation Framework in 2025](https://medium.com/@mahernaija/choosing-the-right-llm-evaluation-framework-in-2025-deepeval-ragas-giskard-langsmith-and-c7133520770c)
- [LLM Evaluation Tools Complete Comparison 2026](https://inference.net/content/llm-evaluation-tools-comparison/)
- [Automated Consistency Analysis of LLMs](https://arxiv.org/pdf/2502.07036)
- [CRIMSON: Clinically-Grounded LLM-Based Metric for Radiology](https://arxiv.org/pdf/2603.06183)
- [FineRadScore: Radiology Report Line-by-Line Evaluation](https://arxiv.org/pdf/2405.20613)

---

## Core Concepts

### 1. Classical NLP Metrics for Consistency Measurement

These metrics were designed for quality evaluation against a reference, but can be repurposed for consistency measurement by treating one LLM output as the "reference" and another as the "candidate" — or by computing all pairwise scores across N outputs.

#### ROUGE (Recall-Oriented Understudy for Gisting Evaluation)

Designed for summarization. Primary variants:

**ROUGE-N** (n-gram overlap):
```
ROUGE-N = Σ_s∈References Σ_ngram∈s Count_match(ngram) / Σ_s∈References Σ_ngram∈s Count(ngram)
```
- ROUGE-1: unigram overlap (word-level)
- ROUGE-2: bigram overlap (phrase-level)
- ROUGE-L: longest common subsequence (captures sentence structure)

**ROUGE-L formula**:
```
Recall_lcs    = LCS(X,Y) / len(Y)
Precision_lcs = LCS(X,Y) / len(X)
F_lcs         = (1+β²) * R_lcs * P_lcs / (R_lcs + β²·P_lcs)
```

**For consistency measurement**: Compute pairwise ROUGE-2 or ROUGE-L between all N outputs. High average pairwise ROUGE = high surface-level consistency.

**Limitations for semantic comparison**:
- Purely lexical — "myocardial infarction" and "heart attack" score 0 similarity
- Does not capture paraphrasing, synonyms, or semantic equivalence
- Sensitive to output length differences
- No handling of word order beyond LCS
- Not suitable for detecting meaning-preserving reformulations common in medical text

#### BLEU (Bilingual Evaluation Understudy)

Originally for machine translation. Formula:
```
BLEU = BP · exp(Σ_n=1^N wn · log(pn))

where:
  pn  = modified n-gram precision for n-grams of order n
  BP  = brevity penalty = exp(1 - r/c) if c < r, else 1
  wn  = uniform weight (typically 1/N)
  c   = length of candidate
  r   = length of reference
```

Modified n-gram precision clips each n-gram count to its maximum count in any reference.

**For consistency**: Treats one output as reference, computes BLEU of another against it. Lower value = more surface variation.

**Limitations**: Same as ROUGE — purely lexical, penalizes valid paraphrases, brevity penalty distorts scores when outputs differ in verbosity.

#### METEOR (Metric for Evaluation of Translation with Explicit ORdering)

More sophisticated than BLEU. Aligns words using exact matches, stemming, synonymy (WordNet), and paraphrase tables.

```
Precision_m = matched_unigrams / output_unigrams
Recall_m    = matched_unigrams / reference_unigrams
F_mean      = 10·P·R / (R + 9·P)
Penalty     = 0.5 · (chunks / matched_unigrams)^3
METEOR      = F_mean · (1 - Penalty)
```

**Advantage over ROUGE/BLEU**: Handles synonyms and stems, so "cardiac" and "heart" may partially match. Penalty term discourages fragmented matches.

**Still limited**: WordNet synonymy doesn't cover medical jargon well (e.g., UMLS concepts). No contextual understanding.

#### Practical Use for Consistency (not quality)

The key adaptation: instead of comparing against a gold-standard reference, compare LLM output_i against LLM output_j. Compute the full N×N pairwise matrix, then summarize:

```python
import numpy as np
from rouge_score import rouge_scorer

def pairwise_consistency(outputs: list[str], metric='rougeL') -> dict:
    scorer = rouge_scorer.RougeScorer([metric], use_stemmer=True)
    n = len(outputs)
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                score = scorer.score(outputs[i], outputs[j])
                matrix[i][j] = getattr(score[metric], 'fmeasure')
    # Average of all off-diagonal elements
    mask = ~np.eye(n, dtype=bool)
    return {
        'mean_pairwise': matrix[mask].mean(),
        'min_pairwise': matrix[mask].min(),
        'std_pairwise': matrix[mask].std()
    }
```

---

### 2. Semantic Similarity Metrics

#### BERTScore

Uses contextual embeddings from transformer models (BERT, RoBERTa, DeBERTa) to compute token-level similarity.

**Algorithm**:
1. Embed candidate tokens: `{c1, c2, ..., cm}` via BERT → contextual vectors
2. Embed reference tokens: `{r1, r2, ..., rn}` via BERT → contextual vectors
3. Build cosine similarity matrix: `sim(i,j) = cos(ci, rj)`

**Formulas**:
```
BERTScore_Precision = (1/m) · Σ_i max_j cos(ci, rj)
BERTScore_Recall    = (1/n) · Σ_j max_i cos(ci, rj)
BERTScore_F1        = 2 · (P · R) / (P + R)
```

**With IDF weighting** (optional, improves performance):
```
IDF(t) = log(N / df(t))
Weighted_P = Σ_i idf(ci) · max_j cos(ci, rj) / Σ_i idf(ci)
```

**For consistency**: Use BERTScore_F1 in pairwise mode across N outputs. Captures semantic similarity even when different words are used (e.g., "hypertension" vs "high blood pressure").

**Advantage over ROUGE**: Understands that "the patient denies chest pain" ≠ "the patient reports chest pain" — different sentiment/polarity — whereas ROUGE would give high overlap.

**Recommended models for medical text**:
- `microsoft/deberta-xlarge-mnli` (highest correlation with human judgment for general text)
- `allenai/scibert_scivocab_uncased` (scientific/biomedical domain)
- `emilyalsentzer/Bio_ClinicalBERT` (clinical notes, trained on MIMIC-III)

**Implementation**:
```python
from evaluate import load

bertscore = load("bertscore")

# For N outputs from same document, compute all pairs
def bertscore_consistency(outputs: list[str], model_type="microsoft/deberta-xlarge-mnli") -> dict:
    n = len(outputs)
    scores = []
    for i in range(n):
        for j in range(i+1, n):
            result = bertscore.compute(
                predictions=[outputs[i]],
                references=[outputs[j]],
                model_type=model_type
            )
            scores.append(result['f1'][0])
    return {
        'mean_semantic_similarity': np.mean(scores),
        'min_semantic_similarity': np.min(scores),
        'std_semantic_similarity': np.std(scores)
    }
```

#### Sentence Embeddings + Cosine Similarity

Encodes entire outputs as dense vectors; cosine distance between them measures semantic consistency.

**Formula**:
```
cosine_similarity(A, B) = (A · B) / (||A|| · ||B||)
```

Values range [−1, 1]; for text embeddings, practically [0, 1] since embeddings are non-negative.

**For consistency across N outputs**:
- Compute N×N similarity matrix
- Report mean off-diagonal similarity, std, min
- Values > 0.90 = high consistency; < 0.75 = concerning variation

**Recommended models**:
- `all-MiniLM-L6-v2`: Fast, 384-dim, good general purpose
- `all-mpnet-base-v2`: Slower, higher quality, 768-dim
- `pritamdeka/S-PubMedBert-MS-MARCO`: Biomedical domain
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`: For multilingual clinical settings

**Implementation**:
```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")

def embedding_consistency(outputs: list[str]) -> dict:
    embeddings = model.encode(outputs, normalize_embeddings=True)
    # Full similarity matrix (dot product = cosine for normalized)
    sim_matrix = embeddings @ embeddings.T
    n = len(outputs)
    # Off-diagonal entries only
    mask = ~np.eye(n, dtype=bool)
    off_diag = sim_matrix[mask]
    return {
        'mean': float(off_diag.mean()),
        'std': float(off_diag.std()),
        'min': float(off_diag.min()),
        'max': float(off_diag.max()),
    }
```

#### Semantic Textual Similarity (STS)

STS benchmarks measure models specifically trained to output similarity on a 0–5 scale. For production consistency pipelines, this can be operationalized using cross-encoder models:

```python
from sentence_transformers import CrossEncoder

model = CrossEncoder('cross-encoder/stsb-roberta-large')

# Pairwise STS scores (0-1 range after sigmoid)
score = model.predict([("summary_run_1", "summary_run_2")])
```

Cross-encoders attend jointly to both texts and are more accurate than bi-encoders for fine-grained comparison, at higher compute cost.

**Semantic vs surface comparison**:
- Surface metrics (ROUGE/BLEU): "The lab results indicate elevated creatinine" vs "Lab results show high creatinine" → low overlap, despite identical meaning
- Semantic metrics (BERTScore/STS): Same pair → high similarity (~0.92 cosine)
- Critical for medical text: abbreviations (HTN=hypertension), paraphrasing by clinicians, passive/active voice shifts all change surface form without changing meaning

---

### 3. LLM-as-Judge Approaches

#### Core Approach

Use a second (or same) LLM to score consistency between two or more outputs. Can operate in several modes:

1. **Pairwise comparison**: Given two outputs A and B for the same document, score their semantic agreement (0–10 or binary)
2. **Reference-anchored**: Given a "gold" summary and a candidate, score factual alignment
3. **Multi-output clustering**: Given N outputs, identify which are semantically equivalent groups

#### Prompting Strategies

**Pairwise comparison prompt template** (recommended for consistency):
```
You are evaluating whether two medical summaries of the same document convey equivalent clinical information.

DOCUMENT: {source_document}
SUMMARY A: {output_1}
SUMMARY B: {output_2}

Rate the clinical consistency between Summary A and Summary B on a scale of 1-5:
5 = Clinically identical — same diagnoses, findings, recommendations
4 = Substantially consistent — minor phrasing differences, same clinical picture
3 = Partially consistent — some important differences in emphasis or inclusion
2 = Inconsistent — different clinical conclusions on key findings
1 = Contradictory — direct factual contradiction

Provide:
1. Score: [1-5]
2. Key differences identified: [list]
3. Any clinically significant discrepancies: [yes/no + explanation]
```

**Chain-of-thought (CoT) prompting**: Ask the model to reason through differences before scoring. Substantially reduces arbitrary variance in scoring.

**Rubric-based scoring**: Provide explicit criteria for each score level. Reduces verbosity bias and positional effects.

**Reference answer grounding**: Include the source document. Anchors the judge to the original facts rather than judging outputs purely relative to each other.

#### Known Biases

**Position Bias**: 
- When shown two outputs in order (A then B), judges systematically favor one position (primacy or recency)
- Magnitude: shifting response order can change accuracy by >10 percentage points
- Varies dramatically by model: Gemini 2.5 Pro (bias=0.002) vs Qwen 3 8B (bias=0.192)
- **Mitigation**: Run each pair in both orderings (AB and BA); report only if consistent. The "position consistency" metric: PC = consistent_evaluations / total_evaluations

**Verbosity Bias**:
- Historical concern (2023-era papers): LLM judges preferred longer responses regardless of quality
- 2025-2026 finding: Verbosity bias has fallen dramatically — all 21 tested judges showed bias < 0.011 under pairwise rubric comparison
- Still worth controlling: normalize outputs to similar lengths if comparing across very different verbosity levels

**Self-Enhancement Bias**:
- Models rate outputs from the same model family higher
- Mitigation: use a judge from a different model family than the generator

**The Reliability-Validity Paradox** (critical finding):
- A judge can be highly reproducible (test-retest α > 0.95) while being systematically wrong
- Qwen 3 8B: reproducibility = 0.992, position bias = 0.192 — deterministically biased
- Reporting raw agreement rates is misleading; use Cohen's κ (kappa)

#### Minimum Viable Validation Protocol (from arxiv 2606.19544)

1. Report Cohen's κ, not raw agreement (raw scores overstate agreement by 33–41 percentage points)
2. Measure position bias via paired AB+BA evaluations
3. Test consistency across ≥ 3 independent runs
4. Validate on ≥ 2 benchmarks with different label distributions
5. Verify position bias < 0.10 when test-retest > 0.95

#### Quantification Metrics for Judge Consistency

**Repetition Stability (RS)**:
```
RS = (1/N) · Σ_j (1/n_j) · max_k |C_k^j|
```
Where N = number of judgments, n_j = number of trials per judgment, C_k^j = count of option k in trial j. RS → 1.0 means highly stable (same answer each time).

**Position Consistency (PC)**:
```
PC = consistent_series / total_series
```
Where a "consistent series" means the judge prefers the same winner regardless of ordering.

**Preference Fairness (PF)**:
```
PF = [(rcn × irr) - (pcn × ipr) - S_min^-] / (S_max^+ - S_min^-) × 2 - 1
```
Range: -1 (always primacy-preferred) to +1 (always recency-preferred); 0 = fair.

---

### 4. Self-Consistency / Sampling Methods

#### Core Methodology

Run the same prompt N times with non-zero temperature (e.g., 0.7–1.0). Measure the distribution of outputs.

**Self-consistency error** (from arxiv 2509.19489):
```
ε(x) = min{p(x), 1−p(x)}
```
Where p(x) is the probability of positive response. ε = 0 means perfectly consistent; ε = 0.5 means essentially random.

**Plug-in estimator from k/n samples**:
```
ε̂(x) = min{k/n, 1 - k/n}
Variance: Var(ε̂) ≤ 1/(4n)
```

#### Optimal Budget Allocation

Given total budget B = m × n (m documents × n repeats per document):

```
Optimal: m* = √(πB/8),  n* = √(8B/π)

Expected squared error ≤ 1/(8m) + 1/(πn) + 1/(2nm)
```

**Practical implication**: For a fixed compute budget, split it roughly 50/50 between number of documents and number of repeats. If evaluating 10 documents, run ~10 repeats each.

**For medical summarization consistency specifically**:

- Run N = 10–20 samples per document at temperature = 0.7–1.0
- N < 5: too noisy for reliable variance estimation
- N = 10: reasonable for most evaluation purposes
- N > 30: diminishing returns unless computing tight confidence intervals

#### Aggregation Methods

1. **Majority vote** (for discrete outputs/classifications): The most common output wins. Useful when output is a structured field with discrete values.

2. **Mean pairwise semantic similarity** (for text): Compute all N(N-1)/2 pairwise scores, report mean and std.

3. **Centroid distance**: Embed all outputs; compute centroid embedding; measure mean distance from centroid.
```python
embeddings = model.encode(outputs)  # shape: (N, D)
centroid = embeddings.mean(axis=0)  # shape: (D,)
distances = 1 - (embeddings @ centroid) / (np.linalg.norm(embeddings, axis=1) * np.linalg.norm(centroid))
variance_score = distances.mean()
```

4. **Entropy over token distributions** (requires model access): If you have logprobs, compute entropy of the output distribution at each token position. High entropy tokens = high uncertainty = likely inconsistency points.

5. **Temperature calibration**:
   - T = 0.1–0.3: Maximum consistency (near-deterministic)
   - T = 0.4–0.6: Balanced — typical production setting
   - T ≥ 0.7: Substantial variation; >30% semantic decline for structured outputs
   - For consistency testing: run at T=0.7 to get a meaningful signal

#### Variance Decomposition

Total variance = prompt variance + temperature variance + model variance

To isolate each:
- Fix prompt, vary temperature → temperature variance
- Fix temperature, vary prompt phrasing → prompt variance  
- Fix both, use different models → model variance

---

### 5. Schema / Structured Output Consistency

#### STED (Semantic Tree Edit Distance)

A purpose-built metric for comparing JSON outputs (arxiv 2512.23712).

**Algorithm**:
1. Parse JSON into tree T=(V,E) with nodes carrying type, label, value, path
2. Compute pairwise update cost between nodes:
```
γ_upd(v1, v2) = ws · γ_struct(v1, v2) + wc · γ_content(v1, v2)
```
Where γ_struct measures structural similarity via embeddings, γ_content uses type-aware value comparison.

3. Optimal subtree matching via Hungarian algorithm:
```
OptimalCost(T1, T2) = min_π [Σ_(i,j)∈π d(c1_i, c2_j) + Σ_unmatched deletion/insertion costs]
```

4. Normalized similarity:
```
STED(T1, T2) = 1 - min(1, [d_matched + λ·Δ_unmatched] / max(|C1|, |C2|))
```
Where λ=0.1 penalizes size differences.

**Consistency score across N generations**:
```
σ̂ = σ / σ_max  (normalized standard deviation)
ConsistencyScore = (1 / (1 + 2σ̂))^α  where α=20 (steepness)
```
This amplifies discrimination in the low-deviation range (most relevant for production).

**STED performance**:
- Semantic equivalents: 0.86–0.90 similarity (correctly recognizes variations like "user_name" vs "userName")
- Structure violations: 0.0 similarity
- Expression variations: 0.981 ± 0.017

#### Field-Level Agreement Metrics

For JSON outputs with known schema:

**Field Accuracy** (fine-grained):
```
FieldAccuracy = (correctly extracted fields across all samples) / (total fields × total samples)
```

**Output Accuracy** (all-or-nothing):
```
OutputAccuracy = samples where ALL fields are correct / total samples
```

**Type Consistency Rate**:
```
TypeConsistency_field = runs where field has expected type / total runs
```

**Value Agreement Rate** (for discrete/categorical fields):
```
ValueAgreement_field = (most_common_value_count) / N_runs
```
E.g., if "diagnosis" field gives "hypertension" 9/10 times = 0.90 agreement rate.

**Practical implementation for medical JSON summaries**:
```python
from collections import Counter
import json

def field_consistency(outputs_json: list[dict], schema_fields: list[str]) -> dict:
    results = {}
    for field in schema_fields:
        values = [o.get(field) for o in outputs_json if field in o]
        if not values:
            results[field] = {'presence_rate': 0}
            continue
        
        presence_rate = len(values) / len(outputs_json)
        value_counts = Counter(str(v) for v in values)
        most_common_value, most_common_count = value_counts.most_common(1)[0]
        agreement_rate = most_common_count / len(values)
        
        results[field] = {
            'presence_rate': presence_rate,
            'agreement_rate': agreement_rate,
            'most_common_value': most_common_value,
            'unique_values': len(value_counts),
        }
    return results
```

**Value range distributions** (for numeric fields like lab values):
- Compute mean, std, min, max across N runs
- High std relative to value range indicates unstable extraction
- For categorical medical fields (normal/abnormal): compute entropy of the distribution

**The JSON Pass Rate vs Value Accuracy gap**: Models produce valid JSON nearly 100% of the time, but value accuracy inside that JSON is 15–25 percentage points lower. Structural conformance is not sufficient — content must be evaluated independently.

---

### 6. Medical / Clinical NLP Specifics

#### RadGraph-F1

Converts clinical reports into entity-relation graphs via NER and relation extraction. Compares two reports by matching graph elements.

**Formula**:
```
Precision = |matched entities ∪ matched relations| / |predicted entities ∪ predicted relations|
Recall    = |matched entities ∪ matched relations| / |reference entities ∪ reference relations|
F1        = 2·P·R / (P+R)
```

Entity types: anatomy, observation (finding/disease). Relation types: suggestive_of, located_at, modify.

**For consistency**: Run RadGraph on two LLM outputs of the same note; F1 measures how much of the clinical entity-relation structure is preserved. High RadGraph-F1 between two LLM outputs = high clinical consistency.

**Performance**: RadGraph model achieves micro-F1 of 0.94 on NER, 0.82 on relation extraction (MIMIC-CXR). Inter-radiologist agreement: Cohen's κ > 0.8.

**Limitation**: Primarily validated for chest X-ray / radiology reports. Not validated for psych evals, lab results, or injury reports specifically.

#### CheXBert

A BERT model fine-tuned to extract 14 predefined thoracic disease labels with 4-class status (positive, negative, uncertain, blank).

**Consistency use**: Run CheXBert on two outputs; compute label agreement (exact match F1 across 14 labels). Same label vector = clinically equivalent summary.

**Limitation**: Only covers 14 diseases; consistently assigns high scores to both correct and incorrect outputs, failing to reflect severity of errors. Very narrow domain.

#### GREEN (Generative Radiology Report Evaluation and Error Notation)

LLM-based metric (2024). Fine-tuned LLM judge that scores a generated report against reference, identifying errors in 6 categories:
1. False report of a finding that is not present
2. Missing a finding that is present
3. Incorrect severity/extent of finding
4. Incorrect location of finding
5. Missing comparison with prior studies
6. Hallucinated comparison with prior studies

**Score**: [0, 1], higher = better clinical agreement with reference.

**Advantage over RadGraph**: Interpretable, handles nuanced clinical language, validated against 6 expert radiologists. Higher correlation with expert error counts than RadGraph-F1.

**For consistency**: Use GREEN to compare two LLM outputs against the source document. Similar GREEN scores = similar clinical accuracy = implicitly consistent.

#### CRIMSON

More recent LLM-based metric specifically for radiology, providing sub-scores by error type. Similar to GREEN but different fine-tuning approach.

#### RadCliQ (Radiology Clinical Quality)

A composite metric found to be most aligned with radiologist opinions. Combines multiple sub-metrics into a single quality signal.

#### RaTEScore

Structured entity-aware metric for medical reports. Computes entity-level matching with semantic understanding (not just exact string match). More robust than exact NER matching.

#### UMLS-Based Evaluation

**Tools for concept extraction**:
- **MetaMap**: Official NLM tool; maps clinical text to UMLS concepts. Performance: recall 0.88, precision 0.89, F1 0.88
- **QuickUMLS**: 135× faster than MetaMap with comparable accuracy; recommended for production pipelines
- **cTAKES** (Apache): Open-source, includes NER, co-reference resolution, assertion detection (negation, uncertainty)
- **ScispaCy**: spaCy-based, supports `en_core_sci_lg` and `en_ner_bc5cdr_md` models; fastest for integration

**UMLS-based consistency metric**:
```python
# Pseudo-code
concepts_A = quickumls.match(output_A)  # returns (CUI, preferred_term, score) tuples
concepts_B = quickumls.match(output_B)

cuis_A = {c['cui'] for c in concepts_A if c['score'] > 0.9}
cuis_B = {c['cui'] for c in concepts_B if c['score'] > 0.9}

jaccard = len(cuis_A & cuis_B) / len(cuis_A | cuis_B)
concept_f1 = 2 * len(cuis_A & cuis_B) / (len(cuis_A) + len(cuis_B))
```
This measures whether both outputs mention the same UMLS concepts, regardless of surface phrasing — critical for medical synonymy.

#### Inter-Annotator Agreement for Clinical NER

When using LLM outputs as "annotations" of clinical documents, inter-rater agreement metrics apply directly.

**Cohen's Kappa** (two raters/models):
```
κ = (p_o - p_e) / (1 - p_e)

p_o = observed agreement = Σ_i f_ii / n
p_e = expected agreement = (1/n²) · Σ_i f_{i+} · f_{+i}
```

Interpretation: κ < 0.4 poor, 0.4–0.6 moderate, 0.6–0.8 good, > 0.8 excellent.

**Fleiss' Kappa** (multiple raters, i.e., N LLM runs):
```
P_i = (1/(N(N-1))) · Σ_j n_ij(n_ij - 1)   [per-item agreement]
P̄   = (1/M) · Σ_i P_i                       [mean observed agreement]
P̄_e = Σ_j p_j²                              [expected agreement]
κ   = (P̄ - P̄_e) / (1 - P̄_e)
```

Where N = number of raters (LLM runs), M = number of items (extracted fields), n_ij = number of raters assigning item i to category j.

**Krippendorff's α**: Preferred over kappa for ordinal/continuous values and missing data — applicable to numeric clinical fields (lab values, severity scores).

**Application to LLM consistency**: Treat each run as a "rater." For categorical fields in extracted JSON (diagnosis: yes/no, severity: mild/moderate/severe), compute Fleiss' κ across N runs. κ > 0.8 across all key fields indicates clinically consistent extraction.

#### Clinical Assertion Detection

Beyond entity extraction, clinical notes contain negation, uncertainty, and historical context:
- "Patient DENIES chest pain" ≠ "Patient has chest pain"
- "Possible fracture" ≠ "Confirmed fracture"

cTAKES includes assertion classification. For consistency, check that LLM outputs agree not just on entity presence but on assertion status (positive/negative/uncertain/historical).

---

### 7. Prompt Sensitivity Measurement

#### Core Distinction

- **Consistency measurement**: Same prompt, same document, repeated N times → measures stochastic variance
- **Prompt sensitivity measurement**: Different prompts (semantically equivalent), same document → measures how much output depends on prompt phrasing

#### Perturbation Taxonomy

From published research (PromptBench, 2024–2025):

1. **Character-level**: Typos, character swaps ("summarize" → "sumamrize")
2. **Word-level**: Synonym substitution ("provide" → "give"), word order changes
3. **Sentence-level**: Paraphrasing while preserving semantics
4. **Semantic-level**: Different instruction framing ("Summarize the lab results" vs "Extract the key findings from this lab report")
5. **Format-level**: Output format instructions (JSON vs prose vs bullet points)
6. **Contextual framing**: Adding/removing persona ("You are a clinical assistant...")

**Finding**: Performance can vary >70% across semantically equivalent prompts; accuracy can swing 76 percentage points on some tasks.

#### Sensitivity Metrics

**PromptSensiScore**: Decoding-confidence-based measure. Requires access to model log-probabilities.

**AUC-E (Area Under the Consistency Curve)**: Unified stability metric as perturbation intensity increases. Computed by:
1. Define perturbation intensity levels (0 = original, 1 = max distortion)
2. Measure output consistency at each level
3. Integrate the consistency curve → AUC-E

**Spearman's rank correlation**: Measures monotonic relationship between prompt variation degree and output divergence.

**Practical sensitivity index**:
```python
def prompt_sensitivity(prompt_variants: list[str], document: str, 
                        model_fn, n_runs_per_prompt=5) -> dict:
    """
    prompt_variants: list of semantically equivalent prompt phrasings
    Returns: sensitivity score (0=insensitive, 1=maximally sensitive)
    """
    all_outputs = {}
    for i, prompt in enumerate(prompt_variants):
        outputs = [model_fn(prompt, document) for _ in range(n_runs_per_prompt)]
        all_outputs[i] = outputs
    
    # Within-prompt variance (baseline)
    within_variances = []
    for outputs in all_outputs.values():
        embs = model.encode(outputs)
        sim_matrix = embs @ embs.T
        within_variances.append(1 - sim_matrix[~np.eye(len(outputs), dtype=bool)].mean())
    
    # Between-prompt variance
    prompt_centroids = {i: model.encode(outs).mean(0) for i, outs in all_outputs.items()}
    centroid_matrix = np.array(list(prompt_centroids.values()))
    sims = centroid_matrix @ centroid_matrix.T
    between_variance = 1 - sims[~np.eye(len(prompt_variants), dtype=bool)].mean()
    
    # Sensitivity = how much between-prompt variance exceeds within-prompt variance
    sensitivity = between_variance / (np.mean(within_variances) + 1e-9)
    
    return {
        'sensitivity_ratio': sensitivity,   # >1 means prompt matters more than temperature
        'between_prompt_variance': between_variance,
        'within_prompt_variance': np.mean(within_variances),
    }
```

#### A/B Prompt Comparison

**Method**: 
1. Define two prompt versions (A = current, B = proposed change)
2. Run both on same set of documents (N ≥ 30 for statistical power)
3. Measure: semantic similarity of outputs, field agreement for JSON, clinical entity overlap
4. Statistical test: paired t-test or Wilcoxon signed-rank on similarity scores

**For medical setting**: Also measure clinical metric agreement (RadGraph-F1 or UMLS concept overlap) in addition to surface metrics. A prompt change that improves ROUGE but decreases clinical entity recall is a regression.

#### Healthcare-Specific Finding (arxiv 2606.07237)

Healthcare LLMs show substantial inconsistency under prompt variation:
- Identical clinical scenarios produce divergent responses under minor prompt adjustments
- Performance differs between general-purpose and specialized medical models
- Sensitivity patterns differ by clinical domain (radiology vs psychiatry vs primary care)
- Practitioners cannot assume stable outputs without explicit stability testing

---

### 8. Practical Tooling

#### RAGAS (Retrieval-Augmented Generation Assessment Suite)

**License**: Apache 2.0  
**Best for**: RAG pipelines, evaluating whether summaries faithfully reflect source documents

**Key metrics for consistency use cases**:
- `Faithfulness`: Breaks response into claims; verifies each against source context. Score = supported_claims / total_claims
- `FactualCorrectness`: Compares factual content of prediction vs reference
- `SemanticSimilarity`: Embedding-based similarity between output and reference
- `BleuScore`, `RougeScore`, `CHRFScore`: Traditional metrics built-in
- `SummarizationScore`: Specifically for summarization tasks

**Installation and basic usage**:
```python
pip install ragas

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall
from datasets import Dataset

# For consistency: treat one output as reference, others as predictions
data = {
    "question": [doc_id] * N,
    "answer": llm_outputs,         # outputs being evaluated
    "contexts": [[source_doc]] * N, # original document as context
    "ground_truth": [reference_summary] * N  # or first output as anchor
}
dataset = Dataset.from_dict(data)
results = evaluate(dataset, metrics=[faithfulness, semantic_similarity])
```

**Limitation**: Designed for RAG evaluation, not pure consistency measurement. Faithfulness requires a reference context.

#### DeepEval

**License**: Apache 2.0  
**Best for**: Unit-test style CI/CD LLM evaluation

**Key metrics**:
- `FaithfulnessMetric`: Factual consistency with context
- `HallucinationMetric`: Detects unsupported claims
- `AnswerRelevancyMetric`: Output relevance to input
- `SummarizationMetric`: Coverage and factual accuracy of summaries
- `GEval`: Custom LLM-graded metric with configurable criteria (most flexible)

**GEval for custom consistency scoring**:
```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

consistency_metric = GEval(
    name="Clinical Consistency",
    criteria="Evaluate whether the actual output conveys the same clinical information as the expected output, including identical diagnoses, findings, and recommendations.",
    evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
    threshold=0.7
)

test_case = LLMTestCase(
    input=source_document,
    actual_output=output_run_2,
    expected_output=output_run_1  # treating first run as anchor
)
consistency_metric.measure(test_case)
```

**ROUGE via scorer module**:
```python
from deepeval.scorer import Scorer
scorer = Scorer()
score = scorer.rouge_score(prediction=output_2, target=output_1, score_type="rougeL")
```

#### Promptfoo

**License**: MIT  
**Best for**: Prompt A/B testing, multi-model comparison, adversarial testing

**Consistency testing via --repeat**:
```bash
promptfoo eval --repeat 10  # runs each test case 10 times, reports variance
```

**Configuration for consistency testing**:
```yaml
prompts:
  - "Summarize the following medical document: {{document}}"
  
providers:
  - openai:gpt-4o

tests:
  - vars:
      document: "{{lab_report}}"
    assert:
      - type: similar
        value: "{{expected_summary}}"
        threshold: 0.85
        metric: semantic_consistency
      - type: llm-rubric
        value: "The summary correctly identifies all abnormal lab values"
        metric: clinical_accuracy
```

**Similarity assertion types**: `similar` (embedding cosine), `contains`, `regex`, `llm-rubric`, `model-graded-closedqa`

**Named metrics**: Tag assertions with `metric:` to aggregate related checks into composite scores displayed in web UI.

#### Giskard

**License**: Apache 2.0  
**Best for**: Automated vulnerability scanning, hallucination detection, bias detection

**Automated scan**:
```python
import giskard
import pandas as pd

# Wrap your model
model = giskard.Model(
    model=your_summarizer_fn,
    model_type="text_generation",
    name="Medical Summarizer",
    description="Summarizes medical documents",
    feature_names=["document"]
)

dataset = giskard.Dataset(
    df=pd.DataFrame({"document": your_test_documents}),
    target=None
)

scan_results = giskard.scan(model, dataset)
scan_results.to_html("scan_report.html")
```

**Detects**: Hallucination/misinformation, output consistency issues, harmful content, prompt injection vulnerability, bias.

#### LangSmith

**License**: Proprietary (free tier available)  
**Best for**: Production tracing + human review when already on LangChain/LangGraph stack

**Evaluator for consistency**:
```python
from langsmith.evaluation import evaluate, LangChainStringEvaluator

evaluator = LangChainStringEvaluator("embedding_distance")  # or "labeled_criteria"

results = evaluate(
    target=your_summarizer,
    data="your-dataset-name",
    evaluators=[evaluator],
    experiment_prefix="consistency-test-v1"
)
```

**Key limitation**: Best used for production monitoring and human review, not batch consistency measurement.

#### HuggingFace `evaluate` Library

**Best for**: Reference implementations of standard metrics (ROUGE, BLEU, BERTScore, METEOR, STS)

```python
import evaluate

# Load any metric by name
rouge = evaluate.load("rouge")
bertscore = evaluate.load("bertscore")
meteor = evaluate.load("meteor")
bleu = evaluate.load("bleu")

# Batch compute
results = rouge.compute(
    predictions=outputs,
    references=[outputs[0]] * len(outputs)  # anchor to first output
)
```

#### `rouge-score` (Google)

```bash
pip install rouge-score
```
```python
from rouge_score import rouge_scorer

scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
scores = scorer.score(reference, prediction)
# Returns named tuple: Score(precision, recall, fmeasure)
```

#### `sentence-transformers`

```bash
pip install sentence-transformers
```
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
# or biomedical: "pritamdeka/S-PubMedBert-MS-MARCO"
embeddings = model.encode(outputs, normalize_embeddings=True)
sim_matrix = embeddings @ embeddings.T
```

#### Summary: Tool Selection Matrix

| Tool | Classical Metrics | Semantic Metrics | LLM-as-Judge | Structured Output | Clinical NLP | Prompt A/B | CI/CD |
|------|---|---|---|---|---|---|---|
| HuggingFace `evaluate` | ✅ | ✅ (BERTScore) | ❌ | ❌ | ❌ | ❌ | Partial |
| `sentence-transformers` | ❌ | ✅ | ❌ | ❌ | ❌ (need domain model) | ❌ | ❌ |
| DeepEval | ✅ | ✅ | ✅ (GEval) | ❌ | ❌ | ❌ | ✅ |
| RAGAS | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | Partial |
| Promptfoo | Partial | ✅ (similar) | ✅ (rubric) | ❌ | ❌ | ✅ | ✅ |
| Giskard | ❌ | ❌ | ✅ (scan) | ❌ | ❌ | ❌ | ✅ |
| LangSmith | ❌ | ✅ | ✅ | ❌ | ❌ | Partial | ✅ |
| RadEval | ✅ | ✅ | ❌ | ❌ | ✅ (radiology) | ❌ | ❌ |
| STED framework | ❌ | ❌ | ❌ | ✅ (JSON) | ❌ | ❌ | ❌ |

---

## Code Snippets

### Full Consistency Pipeline for Medical Document Summarization

```python
import numpy as np
from rouge_score import rouge_scorer as rs
from evaluate import load
from sentence_transformers import SentenceTransformer
from collections import Counter
import json

class MedicalSummarizationConsistencyEvaluator:
    def __init__(self, embedding_model="all-MiniLM-L6-v2"):
        self.rouge = rs.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
        self.bertscore = load("bertscore")
        self.sbert = SentenceTransformer(embedding_model)
    
    def evaluate(self, outputs: list[str], source_doc: str = None) -> dict:
        n = len(outputs)
        assert n >= 2, "Need at least 2 outputs to measure consistency"
        
        # --- Surface metrics ---
        rouge_scores = []
        for i in range(n):
            for j in range(i+1, n):
                s = self.rouge.score(outputs[i], outputs[j])
                rouge_scores.append(s['rougeL'].fmeasure)
        
        # --- Semantic metrics ---
        embeddings = self.sbert.encode(outputs, normalize_embeddings=True)
        sim_matrix = embeddings @ embeddings.T
        mask = ~np.eye(n, dtype=bool)
        semantic_sims = sim_matrix[mask]
        
        # --- BERTScore (subset for efficiency) ---
        bs_scores = []
        for i in range(min(n, 5)):  # cap at 5 to control latency
            for j in range(i+1, min(n, 5)):
                result = self.bertscore.compute(
                    predictions=[outputs[i]],
                    references=[outputs[j]],
                    model_type="microsoft/deberta-xlarge-mnli"
                )
                bs_scores.append(result['f1'][0])
        
        return {
            'rouge_l': {'mean': np.mean(rouge_scores), 'std': np.std(rouge_scores), 'min': min(rouge_scores)},
            'semantic_similarity': {'mean': float(semantic_sims.mean()), 'std': float(semantic_sims.std()), 'min': float(semantic_sims.min())},
            'bertscore_f1': {'mean': np.mean(bs_scores), 'std': np.std(bs_scores)},
            'n_outputs': n,
        }

    def evaluate_json_consistency(self, json_outputs: list[dict], fields: list[str]) -> dict:
        results = {}
        for field in fields:
            values = [str(o.get(field, '__missing__')) for o in json_outputs]
            counts = Counter(values)
            most_common, count = counts.most_common(1)[0]
            results[field] = {
                'agreement_rate': count / len(values),
                'unique_values': len(counts),
                'most_common': most_common,
                'missing_rate': values.count('__missing__') / len(values),
            }
        return results
```

### UMLS Concept Overlap Consistency

```python
# Requires: pip install quickumls
from quickumls import QuickUMLS
import numpy as np

matcher = QuickUMLS('/path/to/quickumls/data', threshold=0.9)

def umls_consistency(outputs: list[str]) -> dict:
    concept_sets = []
    for output in outputs:
        matches = matcher.match(output, best_match=True, ignore_syntax=False)
        cuis = {m[0]['cui'] for m in matches}
        concept_sets.append(cuis)
    
    # Pairwise Jaccard similarity
    n = len(concept_sets)
    jaccards = []
    for i in range(n):
        for j in range(i+1, n):
            intersection = len(concept_sets[i] & concept_sets[j])
            union = len(concept_sets[i] | concept_sets[j])
            jaccards.append(intersection / union if union > 0 else 1.0)
    
    return {
        'mean_concept_jaccard': np.mean(jaccards),
        'min_concept_jaccard': np.min(jaccards),
        'unique_concepts_per_run': [len(s) for s in concept_sets],
    }
```

### LLM-as-Judge for Medical Consistency

```python
from anthropic import Anthropic

client = Anthropic()

JUDGE_PROMPT = """You are a clinical expert evaluating whether two medical summaries convey equivalent clinical information.

SOURCE DOCUMENT:
{source}

SUMMARY A:
{summary_a}

SUMMARY B:
{summary_b}

Rate the clinical consistency on a scale of 1-5:
5 = Clinically identical
4 = Substantially consistent, minor phrasing differences
3 = Partially consistent, some differences in emphasis
2 = Inconsistent, different clinical conclusions
1 = Contradictory, direct factual contradiction

Reason through any differences first, then provide your score.

Response format:
REASONING: <your analysis>
SCORE: <1-5>
KEY_DIFFERENCES: <list or "none">
CLINICALLY_SIGNIFICANT: <yes/no>"""

def judge_consistency(source: str, output_a: str, output_b: str) -> dict:
    # Run in both orders to detect position bias
    results = []
    for a, b in [(output_a, output_b), (output_b, output_a)]:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(source=source, summary_a=a, summary_b=b)
            }]
        )
        text = response.content[0].text
        score_line = [l for l in text.split('\n') if l.startswith('SCORE:')]
        score = int(score_line[0].split(':')[1].strip()) if score_line else None
        results.append(score)
    
    return {
        'score_ab': results[0],
        'score_ba': results[1],
        'position_consistent': results[0] == results[1],
        'mean_score': np.mean([r for r in results if r is not None]),
    }
```

---

## Gotchas & Warnings

### Classical Metrics
- ROUGE/BLEU are inadequate as the *sole* consistency metric for medical text — they will rate "no fracture noted" and "fracture noted" as highly similar (4/5 word overlap). Always pair with semantic metrics.
- ROUGE implementation varies (stemming on/off, tokenization). Use `rouge-score` (Google) consistently; do not mix with NLTK's ROUGE implementation.
- BLEU degrades for long texts; do not use for document-level summarization consistency without normalization.

### BERTScore
- Model choice matters significantly. Using general-purpose BERT on clinical text will miss domain-specific semantics. Use Bio_ClinicalBERT or DeBERTa-xxlarge for best results.
- BERTScore max sequence length is typically 512 tokens; for long medical documents, chunk and aggregate.
- Baseline rescaling makes scores more interpretable but changes the absolute value range; don't mix rescaled and unrescaled scores.

### LLM-as-Judge
- Never trust raw agreement rates; always compute Cohen's κ. Raw rates inflate by 33–41 percentage points.
- Mandatory: run each pair in both orderings (AB and BA) to detect position bias before trusting any judgment.
- Do not use the same model family as judge that was used for generation (self-enhancement bias).
- Smaller models (Qwen 3 8B, Llama 3 8B) show much higher position bias than frontier models; use Claude Opus or Gemini Pro variants for clinical judgment tasks.

### Self-Consistency Sampling
- Running only N=3 is insufficient for reliable variance estimates. Minimum N=10 for production evaluation.
- Temperature = 0 does not guarantee identical outputs across runs due to floating point non-determinism at scale. Test this assumption empirically.
- Budget allocation: if you have B total compute units, split roughly evenly between number of documents (m) and repeats per document (n): m ≈ n ≈ √B.

### JSON / Structured Output
- JSON structural validity (valid JSON) ≠ value accuracy. Always evaluate field values separately from schema conformance.
- The JSON Pass Rate / Value Accuracy gap is 15–25 percentage points across models. Do not report JSON validity as a proxy for output quality.
- Use STED (from arxiv 2512.23712) for semantic comparison of JSON outputs rather than exact-match diff tools like DeepDiff.
- Temperature above 0.7 causes >30% semantic decline in structured outputs for most models (except Claude Sonnet variants which maintain consistency up to T=0.9).

### Clinical / Medical NLP
- RadGraph and CheXBert are validated only for chest X-ray radiology reports. Do not apply to psych evaluations, lab results, or injury reports without revalidation.
- GREEN and CRIMSON require a reference report — cannot be used for pure consistency measurement without a gold standard.
- UMLS tools (QuickUMLS, MetaMap) require local installation of the UMLS Metathesaurus (requires NLM license, free but requires registration).
- Clinical negation is a major failure mode: ensure your consistency metric captures whether assertions (positive/negative/uncertain) are consistent, not just entity presence.
- cTAKES and ScispaCy handle negation detection; generic NLP tools do not.

### Prompt Sensitivity
- Performance can vary >70% across semantically equivalent prompts — never test a prompt with only one phrasing and conclude the system is stable.
- Format-level changes (JSON vs bullet vs prose) often cause larger variation than semantic rephrasing.
- For regulatory/clinical deployment: document prompt sensitivity tests as part of validation. Use at least 5–10 semantically equivalent prompt variants across ≥30 test documents.

### Tooling
- DeepEval's scorer module (ROUGE/BLEU) is explicitly noted as "not useful as LLM metrics" in their own docs — they recommend GEval (LLM-graded) for production use.
- RAGAS is optimized for RAG pipelines; using it for pure generation consistency requires adapting the data format (treating source document as "context").
- Giskard's automated scan is useful for catching classes of vulnerabilities but does not produce the fine-grained field-level metrics needed for clinical validation.
- LangSmith requires LangChain integration; not suitable as a standalone evaluation tool.
- All three major tools (Promptfoo/DeepEval/RAGAS) can be combined: Promptfoo for prompt A/B testing, DeepEval for unit tests in CI, RAGAS for RAG faithfulness scoring.
