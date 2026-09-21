"""
Pathway 1 — Variability evaluator (local variant).

Runs the extraction + rendering pipeline N times with a configurable temperature
and measures how much the outputs vary across runs using three metric layers:
  - Sentence embedding cosine similarity (NeuML/pubmedbert-base-embeddings)
  - BERTScore F1 (microsoft/deberta-large-mnli)
  - TF-IDF cosine (lightweight baseline, zero model download)

Requires local model downloads (~440 MB PubMedBERT, ~900 MB deberta).
For a version that uses Bedrock Titan Embeddings with no local downloads, see
consistency_evaluator_cloud.py.

This is pathway 1 of 2. Pathway 2 (gold standard comparison) will be a separate
tool. The N-run collection function (_collect_runs) is the only shared
infrastructure; do not add reference-based logic here.

Usage:
    pip install -r tools/requirements.txt
    python tools/consistency_evaluator.py \\
        --doc-type lab_result \\
        --document path/to/doc.txt \\
        --prompt prompts/lab_result_prompt.txt \\
        --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \\
        --n-runs 5 \\
        --temperature 0.7 \\
        --output-json results.json
"""

import argparse
import boto3
import itertools
import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
TEMPLATE_DIR = REPO_ROOT / "templates"

DEFAULT_TEMPERATURE = 0.7
DEFAULT_N_RUNS = 5
BERTSCORE_MODEL = "microsoft/deberta-large-mnli"
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"

VALID_DOC_TYPES = frozenset(
    {"lab_result", "doctors_notes", "injury_doc", "visit_assessment", "psych_eval"}
)

TEMPLATE_FILES = {
    "lab_result": "lab_result.j2",
    "doctors_notes": "doctors_notes.j2",
    "injury_doc": "injury_doc.j2",
    "visit_assessment": "visit_assessment.j2",
    "psych_eval": "psych_eval.j2",
}


# ── Infrastructure helpers ────────────────────────────────────────────────────


def _build_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _load_schema(doc_type: str) -> dict:
    schema_file = SCHEMA_DIR / f"{doc_type}_schema.json"
    with open(schema_file) as f:
        return json.load(f)


def _load_models():
    """Loads ML models. Extracted as a standalone function for testability."""
    from sentence_transformers import SentenceTransformer  # lazy — ~440 MB download on first use
    from bert_score import BERTScorer  # lazy — ~900 MB download on first use

    embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    bertscore_scorer = BERTScorer(model_type=BERTSCORE_MODEL, lang="en")
    return embedding_model, bertscore_scorer


def _extract_once(
    bedrock_runtime,
    model_id: str,
    prompt_text: str,
    document_text: str,
    schema: dict,
    doc_type: str,
    temperature: float,
) -> dict:
    """
    Calls bedrock_runtime.converse() directly — not via the extractor handler —
    so that temperature can be freely set. The production handler hardcodes
    temperature=0; this function is the temperature-override path for evaluation.

    WARNING: re-implements the extractor's Bedrock call inline. Future changes
    to the handler's tool schema or prompt handling will not auto-propagate here.
    """
    tool_def = {
        "toolSpec": {
            "name": "extract_document",
            "description": f"Extract structured data from a {doc_type} medical document.",
            "inputSchema": {"json": schema},
        }
    }

    response = bedrock_runtime.converse(
        modelId=model_id,
        system=[{"text": prompt_text}],
        messages=[{"role": "user", "content": [{"text": document_text}]}],
        toolConfig={
            "tools": [tool_def],
            "toolChoice": {"tool": {"name": "extract_document"}},
        },
        inferenceConfig={"maxTokens": 4096, "temperature": temperature},
    )

    content_blocks = response["output"]["message"]["content"]
    tool_use_block = next(
        (block["toolUse"] for block in content_blocks if "toolUse" in block),
        None,
    )
    if tool_use_block is None:
        raise ValueError("Bedrock response did not contain a toolUse block")

    return tool_use_block["input"]


def _render_summary(jinja_env: Environment, doc_type: str, extracted_data: dict) -> str:
    """
    Renders the Jinja2 template for doc_type using extracted_data. Template
    variables are the dict keys themselves, unpacked via **extracted_data —
    identical to the production renderer handler's template.render(**validated_data).
    """
    template = jinja_env.get_template(TEMPLATE_FILES[doc_type])
    return template.render(**extracted_data)


def _collect_runs(
    *,
    bedrock_runtime,
    model_id: str,
    prompt_text: str,
    document_text: str,
    schema: dict,
    doc_type: str,
    temperature: float,
    n_runs: int,
    jinja_env: Environment,
) -> tuple[list[dict], list[str]]:
    """
    Shared infrastructure for both evaluation pathways. Runs extraction +
    rendering N times and returns the raw outputs. Contains no similarity logic.

    Returns:
        extracted_list: one extracted_data dict per run
        summary_list:   one rendered summary string per run
    """
    extracted_list: list[dict] = []
    summary_list: list[str] = []

    for i in range(n_runs):
        logger.info("Run %d/%d", i + 1, n_runs)
        extracted = _extract_once(
            bedrock_runtime, model_id, prompt_text, document_text, schema, doc_type, temperature
        )
        summary = _render_summary(jinja_env, doc_type, extracted)
        extracted_list.append(extracted)
        summary_list.append(summary)

    return extracted_list, summary_list


# ── Metric functions — pathway 1 only ────────────────────────────────────────


def variability_stats(sim_matrix: np.ndarray) -> dict:
    """
    Extracts upper-triangle unique pair scores from an N×N symmetric similarity
    matrix and returns aggregate statistics. All values are plain Python float/int.
    """
    n = sim_matrix.shape[0]
    idx = np.triu_indices(n, k=1)  # excludes diagonal (self-similarity)
    scores = sim_matrix[idx]
    mean = float(np.mean(scores))
    return {
        "n_runs": int(n),
        "n_pairs": int(len(scores)),
        "mean": mean,
        "min": float(np.min(scores)),
        "max": float(np.max(scores)),
        "std": float(np.std(scores)),
        "variance": float(np.var(scores)),
        "cv": float(np.std(scores) / mean) if mean != 0 else None,
    }


def compute_embedding_similarity(texts: list[str], model) -> dict:
    """Pairwise variability across N runs using sentence embeddings (pathway 1)."""
    from sentence_transformers import SentenceTransformer  # noqa: lazy import

    for text in texts:
        if len(text.split()) > 380:
            logger.warning(
                "Text exceeds 380 words — PubMedBERT's 512-token limit may silently truncate it."
            )
            break

    embeddings = model.encode(texts, convert_to_tensor=True)
    sim_matrix = model.similarity(embeddings, embeddings).cpu().numpy()
    return variability_stats(sim_matrix)


def compute_bertscore_similarity(texts: list[str], scorer) -> dict:
    """Pairwise variability across N runs using BERTScore F1 (pathway 1)."""
    from bert_score import BERTScorer  # noqa: lazy import

    texts = texts[:5]  # cap before computing n — latency guard
    n = len(texts)

    for text in texts:
        if len(text.split()) > 380:
            logger.warning(
                "Text exceeds 380 words — BERTScore's 512-token limit may silently truncate it."
            )
            break

    f1_matrix = np.ones((n, n))
    for i, j in itertools.combinations(range(n), 2):
        _, _, F1 = scorer.score([texts[i]], [texts[j]])
        f1_matrix[i, j] = F1.item()  # F1 is a torch.Tensor; .item() extracts the scalar
        f1_matrix[j, i] = F1.item()  # F1 is approximately symmetric

    return variability_stats(f1_matrix)


def compute_tfidf_similarity(texts: list[str]) -> dict:
    """Pairwise variability using TF-IDF cosine. Zero model download baseline (pathway 1)."""
    tfidf_matrix = TfidfVectorizer().fit_transform(texts)
    sim_matrix = sklearn_cosine(tfidf_matrix)
    return variability_stats(sim_matrix)


def compute_json_field_consistency(extracted_list: list[dict]) -> dict:
    """
    Field-level agreement across N extracted JSON outputs.

    Agreement is plurality fraction: max(Counter(values).values()) / N
      All N agree        → 1.0
      2 of 3 agree       → 0.667
      All N different    → 1/N

    Values are normalised via json.dumps before comparison so that equivalent
    nested structures (lists, dicts) compare equal regardless of object identity.
    """
    n = len(extracted_list)
    all_keys: set[str] = set()
    for d in extracted_list:
        all_keys.update(d.keys())

    field_agreement: dict[str, float] = {}
    for key in sorted(all_keys):
        values = [
            json.dumps(d.get(key), sort_keys=True, default=str) for d in extracted_list
        ]
        field_agreement[key] = float(max(Counter(values).values())) / n

    return {"field_agreement": field_agreement}


# ── Orchestration ─────────────────────────────────────────────────────────────


def run_evaluation(args) -> dict:
    document_text = Path(args.document).read_text(encoding="utf-8")
    prompt_text = Path(args.prompt).read_text(encoding="utf-8").strip()
    schema = _load_schema(args.doc_type)
    jinja_env = _build_jinja_env()
    bedrock_runtime = boto3.client("bedrock-runtime", region_name=args.region)

    embedding_model, bertscore_scorer = _load_models()

    extracted_list, summary_list = _collect_runs(
        bedrock_runtime=bedrock_runtime,
        model_id=args.model_id,
        prompt_text=prompt_text,
        document_text=document_text,
        schema=schema,
        doc_type=args.doc_type,
        temperature=args.temperature,
        n_runs=args.n_runs,
        jinja_env=jinja_env,
    )

    return {
        "metadata": {
            "doc_type": args.doc_type,
            "model_id": args.model_id,
            "n_runs": args.n_runs,
            "temperature": args.temperature,
            "embedding_model": EMBEDDING_MODEL,
            "bertscore_model": BERTSCORE_MODEL,
        },
        "text_layer": {
            "embedding_cosine": compute_embedding_similarity(summary_list, embedding_model),
            "bertscore_f1": compute_bertscore_similarity(summary_list, bertscore_scorer),
            "tfidf_cosine": compute_tfidf_similarity(summary_list),
        },
        "json_layer": compute_json_field_consistency(extracted_list),
    }


def _print_report(results: dict) -> None:
    m = results["metadata"]
    print("\n=== Consistency Evaluation Report (Pathway 1 — Variability, local) ===")
    print(f"Doc type:    {m['doc_type']}")
    print(f"Model:       {m['model_id']}")
    print(f"Runs:        {m['n_runs']}  |  Temperature: {m['temperature']}")
    print()
    print("── Text layer (rendered summary) ──")
    for metric_key, label in [
        ("embedding_cosine", f"Embedding cosine  ({m['embedding_model'].split('/')[-1]})"),
        ("bertscore_f1", f"BERTScore F1      ({m['bertscore_model'].split('/')[-1]})"),
        ("tfidf_cosine", "TF-IDF cosine     (baseline)"),
    ]:
        s = results["text_layer"][metric_key]
        cv_str = f"{s['cv']:.4f}" if s["cv"] is not None else "N/A"
        print(f"  {label}")
        print(f"    mean={s['mean']:.4f}  min={s['min']:.4f}  std={s['std']:.4f}  cv={cv_str}")
    print()
    print("── JSON layer (field agreement) ──")
    for field, score in sorted(results["json_layer"]["field_agreement"].items()):
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        print(f"  {field:<30} {bar}  {score:.3f}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure output variability across N runs — local variant with PubMedBERT + BERTScore."
    )
    parser.add_argument("--doc-type", required=True, choices=sorted(VALID_DOC_TYPES))
    parser.add_argument("--document", required=True, help="Path to the document file to process")
    parser.add_argument(
        "--prompt",
        required=True,
        help=(
            "Path to a plain-text prompt file. "
            "This must match the pinned Bedrock Prompt Management version used in production."
        ),
    )
    parser.add_argument(
        "--model-id",
        required=True,
        help="Bedrock model ID including geo prefix (e.g. us.anthropic.claude-sonnet-4-5-20250929-v1:0)",
    )
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS, metavar="N")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--output-json", metavar="PATH", help="Write full JSON results to this path")
    parser.add_argument("--region", default="us-east-1")

    args = parser.parse_args()
    if args.n_runs < 2:
        parser.error("--n-runs must be at least 2")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    results = run_evaluation(args)
    _print_report(results)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        logger.info("Results written to %s", args.output_json)


if __name__ == "__main__":
    main()
