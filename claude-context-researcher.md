# Research Findings

## Source URLs

- [Synthea Official Site](https://synthetichealth.github.io/synthea/) — **Official**
- [Synthea GitHub Repository](https://github.com/synthetichealth/synthea) — **Official**
- [Synthea Wiki: Records](https://github.com/synthetichealth/synthea/wiki/Records) — **Official**
- [Synthea Wiki: Frequently Asked Questions](https://github.com/synthetichealth/synthea/wiki/Frequently-Asked-Questions) — **Official**
- [Synthea synthea.properties config](https://github.com/synthetichealth/synthea/blob/master/src/main/resources/synthea.properties) — **Official**
- [Synthea Exporter.java source](https://github.com/synthetichealth/synthea/blob/master/src/main/java/org/mitre/synthea/export/Exporter.java) — **Official**
- [Synthea ClinicalNoteExporter.java source](https://github.com/synthetichealth/synthea/blob/master/src/main/java/org/mitre/synthea/export/ClinicalNoteExporter.java) — **Official**
- [Synthea note.ftl FreeMarker template](https://github.com/synthetichealth/synthea/blob/master/src/main/resources/templates/notes/note.ftl) — **Official**
- [Synthea chatty-notes GitHub](https://github.com/synthetichealth/chatty-notes) — **Official** (Synthea org tool)
- [MITRE FHIR for Research: Synthea Overview](https://mitre.github.io/fhir-for-research/modules/synthea-overview) — **Official** (MITRE/vendor)
- [NHS England: synthetic_clinical_notes GitHub](https://github.com/nhsengland/synthetic_clinical_notes) — Semi-official (government health org)
- [Claude Academy: Generating Test Datasets](https://academy.claude.com/courses/claude-with-amazon-bedrock/generating-test-datasets) — **Official** (Anthropic)
- [MedSynth GitHub (e2llm)](https://github.com/e2llm/medsynth) — Semi-official (GitHub project, no vendor affiliation confirmed)
- [Tonic Textual product page](https://www.tonic.ai/products/textual) — Semi-official (vendor product page)
- [Synthea Clinical Notes Issue #286](https://github.com/synthetichealth/synthea/issues/286) — Semi-official (GitHub issue thread)
- [TIET-AI tietai-synthea Issue #43](https://github.com/TIET-AI/tietai-synthea/issues/43) — Semi-official (GitHub issue thread)

## Core Concepts

### What Synthea Is

Synthea (synthetichealth.github.io/synthea) is a Java-based open-source synthetic patient population simulator maintained by MITRE. It models patient medical histories using clinical disease modules and population-level statistics from CDC/NIH sources. Its primary design goal is producing interoperable structured health data, not human-readable documents.

### Synthea Output Formats

Synthea's default and primary output formats are **structured data standards**:

- **FHIR** (R4, STU3, DSTU2) — JSON only, no XML. This is the default output.
- **C-CDA** (Consolidated Clinical Document Architecture) — XML-based structured clinical document standard
- **CSV** — Multiple patients per file, tabular
- **CPCDS** — Common Payer Consumer Data Set
- **BFD RIF** — CMS Beneficiary & Family Oriented format
- **JSON** — Synthea-internal format with simulation metadata

There is **no PDF output**. Synthea does not natively produce PDF files at all.

### Synthea's Text and Clinical Note Exporters

There are two relevant text-adjacent export options, both disabled by default in `synthea.properties`:

1. **`exporter.text.export = true`** — Produces one UTF-8 `.txt` file per patient, a human-readable chronological summary of the full patient record. It is explicitly described in the wiki as "a quick human readable format that doesn't adhere to any particular standard." It is not a clinical document; it is a flat dump of the patient record.

2. **`exporter.text.per_encounter_export = true`** — Produces one text file per encounter instead of per patient.

3. **`exporter.clinical_note.export = true`** — Produces `.txt` files in a `notes/` subdirectory. These are generated using a FreeMarker template (`templates/notes/note.ftl`) and contain structured-ish SOAP-style sections:
   - Chief Complaint
   - History of Present Illness (demographics + active conditions)
   - Social History (marital status, housing, smoking/alcohol, socioeconomic data)
   - Allergies
   - Medications
   - Assessment and Plan (conditions + clinical notes)
   - Plan (immunizations, procedures, lab reports, prescribed meds, care plans)

The clinical note output is **one note per encounter** in markdown-adjacent plain text. It reads like a real SOAP note but is formulaic — generated from a template, not prose narrative. Notes cover general outpatient/inpatient encounters only; there is no built-in psych eval, injury report, or specialist document type.

The template-based notes are noted in GitHub issues as "bundled but unused in the original project" in earlier versions; later commits enabled the ClinicalNoteExporter. The content is realistic in structure but sparse in narrative richness.

### Synthea + chatty-notes Bridge

The Synthea organization publishes a separate tool called **chatty-notes** (`github.com/synthetichealth/chatty-notes`) that:
1. Reads a Synthea FHIR Bundle JSON file
2. Extracts encounter data from related FHIR resources
3. Builds a prompt and calls the **OpenAI Chat Completions API**
4. Writes the LLM-generated note to an output directory

This is a two-step workflow: Synthea generates structured patient data → chatty-notes converts it to LLM-written prose clinical notes. Output is plain text. It requires an OpenAI API key and does not natively support Bedrock or Anthropic Claude, though the pattern is reproducible with any LLM API.

### The Fundamental Mismatch

The pipeline described (PDF/text file upload → Bedrock → classification + extraction) needs **documents that look like what a real person would upload**: a scanned lab result, a typed doctor's note, a PDF injury report, a psych eval form. Synthea produces **database-shaped records** — structured FHIR bundles or flat text dumps of patient histories. Converting Synthea output into realistic-looking individual document files requires significant custom engineering.

---

## Code Snippets

### Enabling Synthea text and clinical note export
```properties
# in src/main/resources/synthea.properties
exporter.text.export = true
exporter.text.per_encounter_export = true
exporter.clinical_note.export = true
```

### Synthea CLI to generate N patients
```bash
./run_synthea -p 100
# Output lands in ./output/fhir/ (FHIR R4 default)
# With text enabled: ./output/text/ and ./output/notes/
```

### chatty-notes usage pattern (OpenAI dependency)
```bash
# Set OPENAI_API_KEY, then:
python chatty.py --input ./output/fhir/patient_bundle.json --output ./notes/
```

### Synthea clinical note structure (from note.ftl template)
```
## Chief Complaint
No complaints.

## History of Present Illness
Patient is a 52 year-old non-Hispanic white male. Patient has a history of
hypertension, type 2 diabetes mellitus.

## Social History
Patient is married. Patient is a nonsmoker.
...

## Allergies
No Known Allergies.

## Medications
lisinopril 10 MG Oral Tablet; metformin hydrochloride 500 MG Oral Tablet

## Assessment and Plan
Patient is presenting with type 2 diabetes mellitus, hypertension.

### Plan
- Hemoglobin A1c measurement (procedure)
- Urine protein test (procedure)
```

---

## Gotchas & Warnings

### Synthea

- **No PDF output, ever.** Synthea has no PDF exporter. Getting PDF output requires a separate rendering step (e.g., python-reportlab, WeasyPrint, or a headless browser over the text/HTML).
- **Clinical notes are template-generated, not prose.** The built-in notes are structured from a FreeMarker template — predictable and machine-readable but not the naturalistic narrative prose a real doctor would write. For testing an AI classifier, this may cause the model to find patterns that don't generalize to real documents.
- **No specialist document types.** Synthea has no built-in psych eval, injury report, or visit assessment document type. The disease modules cover conditions, but the note template is generic for all encounters. Lab results exist as FHIR DiagnosticReport resources, not as formatted report documents.
- **Java runtime required.** Synthea is a Java application. It requires JDK 11+ and runs via Gradle. Not pip-installable.
- **Conversion pipeline is non-trivial.** Going from FHIR JSON → formatted text documents that resemble real uploads requires: parsing the FHIR bundle, extracting relevant resources by type, rendering them into a believable document format, and optionally converting to PDF. This is several hundred lines of engineering work.
- **chatty-notes is OpenAI-only.** It calls OpenAI Chat Completions and is not wired to Bedrock. You'd need to fork and modify it to use Bedrock's converse API.
- **Pre-generated downloads are FHIR/CSV only.** The MITRE downloads page (synthea.mitre.org/downloads) offers pre-built datasets in FHIR and CSV. No text document downloads are available.

### LLM-Direct Generation (Using Bedrock/Claude Directly)

> ⚠️ **[TENTATIVE — unofficial source]** The Anthropic Claude Academy lesson on test dataset generation recommends using Claude itself (with Haiku for cost efficiency) to batch-generate structured test data directly from a detailed prompt. This is described as the fastest path to domain-specific evaluation datasets. Source: academy.claude.com/courses/claude-with-amazon-bedrock/generating-test-datasets

This approach — writing a prompt that describes each document type and calling Bedrock in a loop — bypasses the entire Synthea pipeline and produces documents ready to drop into the pipeline immediately, in whatever format you specify (plain text, Markdown, or rendered to PDF).

### MedSynth

> ⚠️ **[TENTATIVE — unverified, unofficial source]** MedSynth (github.com/e2llm/medsynth) claims to generate discharge summaries, lab reports, referral documents, and visit notes with locale-specific schema variance and OCR artifact simulation. Output is NDJSON (structured JSON), not flat text files or PDFs. LLM-generated free-text fields are optional. This tool appears to be a newer, less-established project with no clear institutional backing. Its maturity and maintenance status are unknown.

### NHS England synthetic_clinical_notes

This is a semi-official project from NHS England that uses GPT-4o to generate realistic longitudinal clinical notes for entire hospital stays. It outputs plain text files. It is designed for discharge summary testing, not the document types needed here (psych eval, injury report, lab result). Requires OpenAI API access. Source: github.com/nhsengland/synthetic_clinical_notes

### Tonic Textual

Tonic Textual is a commercial product for de-identifying and re-synthesizing existing real clinical documents (lab reports, discharge notes, EMR records). It is not a generator of documents from scratch — it requires real documents as input to produce synthetic equivalents. Relevant if you have access to real de-identified documents to use as templates. Source: tonic.ai/products/textual

---

## Summary: Trade-offs for This Use Case

| Approach | Output Format | Covers All 5 Doc Types | Setup Effort | LLM Needed | Cost |
|---|---|---|---|---|---|
| Synthea (text/note exporter) | Plain text (template SOAP) | No (general encounters only) | Medium (Java setup + config) | No | Free |
| Synthea + chatty-notes | Plain text prose | No (general encounters only) | High (Java + OpenAI integration) | Yes (OpenAI) | API costs |
| Synthea FHIR → custom renderer | Text or PDF | Partially (with work) | Very High | Optional | Free + dev time |
| Direct LLM prompting (Bedrock/Claude) | Whatever you specify | Yes | Low | Yes (already available) | API costs (low) |
| NHS synthetic_clinical_notes | Plain text | No (discharge only) | Medium | Yes (OpenAI) | API costs |
| MedSynth | NDJSON | Partially | Low | Optional | Free |
| Tonic Textual | Text/PDF (de-identified) | Yes (if templates exist) | Low | No | Commercial |
| Hand-written templates + Faker | Text or PDF | Yes | Low-Medium | No | Free |

**Practical recommendation for a developer testing a Bedrock AI pipeline:** The fastest path to the five specific document types (lab results, doctor's notes, injury documents, visit assessments, psych evals) is to write a small script that calls Bedrock Claude directly with a detailed prompt per document type, collect the plain-text output, and optionally render to PDF using reportlab or weasyprint. This takes a few hours versus days of Synthea plumbing, produces more naturalistic prose than Synthea's template output, and directly exercises the same model being tested (useful for adversarial edge case generation). Synthea is valuable if you need medically coherent patient histories with consistent demographics across documents — but for classifier/extractor testing where you just need realistic-looking individual documents, direct LLM generation is significantly faster.
