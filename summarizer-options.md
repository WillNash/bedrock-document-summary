# Medical Data Summarization with Amazon Bedrock — Options

## Problem

Patient data arrives in many forms: lab results, doctor's notes, injury documentation, psych evaluations, visit assessments. The goal is to produce summary documents that are consistent in structure, tone, and completeness regardless of input variation.

The core tension is **flexibility** (patient data varies wildly) vs. **consistency** (summaries must be uniform).

---

## Approaches to Consistency

### 1. Structured Output / JSON Schema Enforcement

Don't ask the model to write a summary — ask it to fill a schema. Render the validated schema to a human-readable document as a separate step.

- Define per-document-type schemas (`LabResultSummary`, `PsychEvalSummary`, `InjuryDocSummary`, etc.)
- Use Bedrock's Converse API with `toolUse` to force structured extraction
- Validate the returned JSON before rendering
- Render JSON → consistently formatted summary via a template

**Strengths:** Consistency by construction. Missing fields are detectable. Format never drifts. Easy to test and validate.

**Best for:** High-volume, well-defined document types where field coverage matters.

---

### 2. Document-Type Routing + Specialized Prompts

Classify the incoming document first, then route to a type-specific prompt template. A psych eval summary requires different fields and framing than a CBC lab result.

- Classifier step (lightweight model call or rules-based on document metadata)
- Per-type system prompts with explicit section headers, required fields, and length constraints
- Use **Bedrock Prompt Management** to version and lock prompts

**Strengths:** Tailored output per document type. Prompt versioning supports audit trails — important for healthcare.

**Best for:** Organizations that need traceable, reproducible prompt behavior over time.

---

### 3. Few-Shot Examples in Prompt

Include 2–3 gold-standard human-written summaries per document type in the system prompt. Models follow demonstrated format very reliably.

- Works best combined with approach 1 or 2
- Higher token cost per call
- Particularly effective for nuanced clinical tone and terminology

**Strengths:** Strong format adherence. Captures institutional voice and style naturally.

**Best for:** Cases where you have existing high-quality summaries to use as examples, or where tone is as important as structure.

---

### 4. Multi-Step Pipeline (Extract → Normalize → Summarize)

Split the work across multiple model calls:

1. **Extract** — pull raw facts (dates, values, findings, medications) into structured form
2. **Normalize** — handle abbreviations, unit conversions, missing or ambiguous fields
3. **Summarize** — generate the final document from the normalized representation

**Strengths:** More robust to messy or inconsistent input. Each step is independently testable and replaceable. Errors are easier to locate and correct.

**Best for:** Messy real-world input with inconsistent formatting, mixed handwritten/typed sources, or OCR'd documents.

---

## Options 1 vs 2: Detailed Comparison

These two options operate at different layers — which is why comparing them directly is useful, and why they're ultimately complementary rather than alternatives.

**Option 1 (Schema enforcement)** controls consistency at the **output data level**. The model fills fields; your code renders prose. Consistency is guaranteed structurally — if the schema says `lab_result.hemoglobin_g_dl` is a required float, you'll always get it or a validation error.

**Option 2 (Routing + specialized prompts)** controls consistency at the **instruction level**. You're telling the model what to write and how. Consistency depends on how well the model follows instructions, which is less deterministic.

### Where Consistency is Enforced

Option 1 enforces it in code — schema validation happens before the summary is rendered. A missing required field is a detectable, catchable error. Option 2 enforces it in the prompt — if the model drifts or misses a section, nothing breaks, you just get a worse summary.

### Output Generation Path

Option 1: `source doc → model fills schema → validate JSON → code renders prose`
Option 2: `source doc → model writes prose directly from prompt instructions`

The rendering step in Option 1 is significant. Summary format is controlled by a template, not the model — changing the layout doesn't require touching the prompt or rerunning inference.

### Handling Missing Information

Option 1: a missing field is an explicit `null` in the schema. You know exactly what's absent and can handle it consistently in the renderer (e.g. "Not documented").

Option 2: the model decides how to handle missing information — it might omit the section, say "not mentioned," or hallucinate a value. Inconsistent by nature.

### Clinical Nuance and Judgment

Option 1 is constrained by predefined fields. Nuance that doesn't map to a schema field gets lost or crammed into a catch-all text field. A psych evaluation may have contextual observations that don't fit neatly into structured fields.

Option 2 lets the model exercise clinical judgment about framing, emphasis, and what's worth including. Better for complex, narrative-heavy documents.

### Schema Design Cost

Option 1 requires upfront work defining schemas per document type, and ongoing maintenance when new fields emerge. This is non-trivial for complex documents like psych evals.

Option 2 requires well-crafted prompts, but they're easier to iterate on than schemas.

### Testability

Option 1: unit tests against the schema — did the output include all required fields? Are values the right types? Are any values outside expected ranges?

Option 2: testing requires model-based evaluation or human review — harder to automate.

### Summary Table

| | Option 1: Schema | Option 2: Prompt routing |
|---|---|---|
| Consistency enforced by | Code (schema validation) | Model instruction following |
| Missing fields | Explicit null, detectable | Model decides, inconsistent |
| Output format control | Code template | Model-generated prose |
| Clinical nuance | Limited to predefined fields | Model exercises judgment |
| Testability | Automated (unit tests) | Requires eval or human review |
| Setup cost | Schema design per doc type | Prompt design per doc type |
| Best for | Structured, data-heavy docs | Narrative, judgment-heavy docs |

### They're Not Mutually Exclusive

Option 2's routing (classify → apply type-specific config) is needed regardless of which output approach you use. A mature system uses both:

```
Incoming document
      │
      ▼
[Classifier] ← Option 2's routing
      │
      ├─► Lab result   → LabResultSchema  (Option 1 — structured)
      ├─► Psych eval   → PsychEvalPrompt  (Option 2 — narrative)
      └─► Injury doc   → InjuryDocSchema  (Option 1 — structured)
```

A reasonable split: use schema enforcement (Option 1) for data-heavy documents like lab results where fields are well-defined. Use prompt-guided prose (Option 2) for narrative documents like psych evaluations where clinical framing matters more than field coverage.

---

## Validation and Adversarial Agents

A validation layer is worth considering, particularly for high-stakes document types like psych evaluations, injury reports, or anything feeding into legal or treatment decisions.

### Agent Roles

**Factual grounding agent** — checks every claim in the summary against the source document. Catches hallucinations, wrong values (e.g. an incorrect lab number), and information conflated across patients in bulk processing. Prompted to return specific contradictions with source evidence, not just a pass/fail.

**Completeness agent** — reads the source document looking for important findings that *didn't* make it into the summary. Distinct from factual grounding: a summary can be accurate but still omit a critical detail. Especially relevant for complex documents with multiple sections.

**Schema/format validator** — checks that required fields are present, values are within expected bounds, and structure matches the template. This doesn't need a model if you're using structured output — pure code validation at the JSON level before rendering.

**Adversarial/red-team agent** — prompted to assume the summary is wrong and find evidence for that position. More aggressive than a neutral checker. Useful when errors carry significant consequences.

### Judge-Critic Loop Pattern

```
Source document
      │
      ▼
 [Summarizer] ──► Draft summary
                        │
                        ▼
              [Critic agent(s)]
                        │
               ┌────────┴────────┐
            Issues            No issues
            found               │
               │                ▼
               ▼           Accept summary
          [Revise]
               │
               ▼
          Re-check
        (max N iterations)
```

The critic returns structured output — specific issues with source references — so the summarizer has actionable feedback, not vague critique. Set a hard iteration cap (2–3 is usually enough) and surface any unresolved flags for human review rather than looping indefinitely.

### Cost Tradeoff

Validation roughly doubles or triples inference calls per document. A reasonable approach is to tier by document type:

| Document Type | Suggested Validation |
|---|---|
| Lab results | Schema validation only (code-level) |
| Doctor's notes / visit summaries | Factual grounding agent |
| Injury documentation | Factual grounding + completeness agent |
| Psych evaluations | Full critic loop + human review flag |

### Using Existing Summaries for Validation

If you have existing human-written summaries, a model-as-judge agent can compare new summaries against them for structural and tonal consistency — not just factual accuracy. This gives you a measurable drift signal over time as prompts or models change.

---

## Bedrock-Specific Features

| Feature | Relevance |
|---|---|
| **Converse API + tool use** | Forces structured/schema output — the primary mechanism for approach 1 |
| **Prompt Management** | Versioned, locked prompts — consistency across time and deployments, supports audit |
| **Guardrails** | PHI redaction, topic filtering, output content validation |
| **Batch Inference** | Efficient processing of large volumes of existing records |
| **Agents** | Multi-step pipelines with state if the workflow requires orchestration |
| **Knowledge Bases** | If summaries should reference clinical guidelines or institutional standards |

**Model choice:** Claude models (Sonnet 4.6 / Opus 4.7) significantly outperform other Bedrock-available models for clinical language understanding and instruction following.

---

## Recommended Starting Point

**Schema enforcement + document-type routing + Prompt Management:**

1. Define JSON schemas per document type
2. Use `toolUse` in the Converse API to extract into the schema
3. Validate the JSON, then render to a summary using a per-type template
4. Store and version prompts in Bedrock Prompt Management

This gives consistency by construction, auditability through prompt versioning, and testability at the schema validation step. Few-shot examples can be layered on once you have baseline summaries to reference.

---

## Open Questions Before Implementation

- ~~Do you have existing human-written summaries?~~ Yes — use for few-shot examples, schema derivation, and as a model-as-judge baseline for consistency validation.
- Are document types known at ingestion time, or does classification need to happen inline?
- What is the required output format — structured data, plain prose, or both?
- HIPAA/compliance scope: are documents being sent to Bedrock with PHI, and is your AWS environment BAA-covered?
