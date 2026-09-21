"""
Tests for tools/consistency_evaluator_cloud.py — pathway 1, cloud variant.

No real Bedrock calls or model downloads are made — embedding similarity is tested
by mocking bedrock_runtime.invoke_model() to return known embedding vectors.
"""

import contextlib
import importlib as _importlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

# ── Dependency availability check ─────────────────────────────────────────────
_MISSING_DEPS = [
    m for m in ("numpy", "sklearn")
    if _importlib.util.find_spec(m) is None
]
pytestmark = pytest.mark.skipif(
    bool(_MISSING_DEPS), reason=f"Missing deps: {_MISSING_DEPS}"
)

# ── Load consistency_evaluator from tools/ ────────────────────────────────────
_TOOLS_DIR = Path(__file__).parent.parent / "tools"
_spec = importlib.util.spec_from_file_location(
    "consistency_evaluator_cloud", _TOOLS_DIR / "consistency_evaluator_cloud.py"
)
_mod = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_mod)
except ImportError as _e:
    pytest.skip(f"consistency_evaluator import failed: {_e}", allow_module_level=True)

sys.modules["consistency_evaluator_cloud"] = _mod

import numpy as np

variability_stats = _mod.variability_stats
compute_tfidf_similarity = _mod.compute_tfidf_similarity
compute_json_field_consistency = _mod.compute_json_field_consistency
compute_embedding_similarity = _mod.compute_embedding_similarity
run_evaluation = _mod.run_evaluation


# ── Helpers ───────────────────────────────────────────────────────────────────


def _embedding_mock(vectors: list[list[float]]):
    """Returns a mock bedrock_runtime whose invoke_model yields the given embedding vectors."""
    br = mock.MagicMock()
    responses = []
    for vec in vectors:
        body = json.dumps({"embedding": vec, "inputTextTokenCount": len(vec)}).encode()
        responses.append({"body": io.BytesIO(body)})
    br.invoke_model.side_effect = responses
    return br


# ── TestVariabilityStats ───────────────────────────────────────────────────────


class TestVariabilityStats:
    def test_identical_runs_mean_is_one(self):
        matrix = np.ones((3, 3))
        result = variability_stats(matrix)
        assert result["mean"] == pytest.approx(1.0)
        assert result["std"] == pytest.approx(0.0)
        assert result["n_runs"] == 3
        assert result["n_pairs"] == 3  # 3 choose 2

    def test_two_run_single_pair(self):
        matrix = np.array([[1.0, 0.8], [0.8, 1.0]])
        result = variability_stats(matrix)
        assert result["n_pairs"] == 1
        assert result["mean"] == pytest.approx(0.8)
        assert result["cv"] == pytest.approx(0.0)

    def test_five_run_known_values(self):
        matrix = np.full((5, 5), 0.9)
        np.fill_diagonal(matrix, 1.0)
        matrix[0, 1] = matrix[1, 0] = 0.7
        result = variability_stats(matrix)
        assert result["n_pairs"] == 10  # 5 choose 2
        assert result["min"] == pytest.approx(0.7)
        assert result["max"] == pytest.approx(0.9)
        assert result["mean"] == pytest.approx((0.7 + 9 * 0.9) / 10)

    def test_cv_is_none_when_mean_is_zero(self):
        matrix = np.zeros((3, 3))
        result = variability_stats(matrix)
        assert result["cv"] is None

    def test_diagonal_excluded_from_mean(self):
        matrix = np.array([[1.0, 0.5, 0.5], [0.5, 1.0, 0.5], [0.5, 0.5, 1.0]])
        result = variability_stats(matrix)
        assert result["mean"] == pytest.approx(0.5)

    def test_all_values_are_plain_python_types(self):
        matrix = np.full((3, 3), 0.9)
        np.fill_diagonal(matrix, 1.0)
        result = variability_stats(matrix)
        for key, val in result.items():
            if val is not None:
                assert type(val) in (int, float), f"{key} returned {type(val)}"


# ── TestTfidfSimilarity ────────────────────────────────────────────────────────


class TestTfidfSimilarity:
    def test_identical_texts_high_similarity(self):
        texts = ["the patient has lab results showing elevated glucose"] * 3
        result = compute_tfidf_similarity(texts)
        assert result["mean"] > 0.99

    def test_completely_different_texts_low_similarity(self):
        texts = ["alpha bravo charlie delta", "echo foxtrot golf hotel", "india juliet kilo lima"]
        result = compute_tfidf_similarity(texts)
        assert result["mean"] == pytest.approx(0.0)

    def test_partial_overlap_intermediate_similarity(self):
        texts = [
            "patient blood glucose elevated hemoglobin",
            "patient blood pressure normal hemoglobin",
            "doctor visit prescription medicine refill",
        ]
        result = compute_tfidf_similarity(texts)
        assert 0.0 < result["mean"] < 1.0

    def test_returns_expected_keys(self):
        result = compute_tfidf_similarity(["text one", "text two", "text three"])
        assert set(result.keys()) == {"n_runs", "n_pairs", "mean", "min", "max", "std", "variance", "cv"}

    def test_minimum_two_runs(self):
        result = compute_tfidf_similarity(["first text here", "second text there"])
        assert result["n_pairs"] == 1
        assert isinstance(result, dict)


# ── TestJsonFieldConsistency ───────────────────────────────────────────────────


class TestJsonFieldConsistency:
    def test_all_identical_gives_full_agreement(self):
        data = [{"glucose": 5.5, "hba1c": 6.2}] * 3
        result = compute_json_field_consistency(data)
        for score in result["field_agreement"].values():
            assert score == pytest.approx(1.0)

    def test_all_different_gives_minimum_agreement(self):
        data = [{"glucose": 5.5}, {"glucose": 6.0}, {"glucose": 7.1}]
        result = compute_json_field_consistency(data)
        assert result["field_agreement"]["glucose"] == pytest.approx(1 / 3)

    def test_partial_agreement(self):
        data = [{"status": "normal"}, {"status": "normal"}, {"status": "elevated"}]
        result = compute_json_field_consistency(data)
        assert result["field_agreement"]["status"] == pytest.approx(2 / 3)

    def test_missing_field_treated_as_distinct_value(self):
        data = [{"glucose": 5.5, "notes": "none"}, {"glucose": 5.5}, {"glucose": 5.5}]
        result = compute_json_field_consistency(data)
        assert "notes" in result["field_agreement"]
        # "none" appears once, None (absent) appears twice → plurality is 2/3
        assert result["field_agreement"]["notes"] == pytest.approx(2 / 3)

    def test_nested_dict_serialized_for_comparison(self):
        same = {"panels": [{"name": "CBC", "value": 4.5}]}
        diff = {"panels": [{"name": "BMP", "value": 3.0}]}
        data = [same, same, diff]
        result = compute_json_field_consistency(data)
        assert result["field_agreement"]["panels"] == pytest.approx(2 / 3)


# ── TestEmbeddingSimilarity ────────────────────────────────────────────────────


class TestEmbeddingSimilarity:
    def test_identical_embeddings_give_similarity_one(self):
        vec = [1.0, 0.0, 0.0, 0.0]
        br = _embedding_mock([vec, vec, vec])
        result = compute_embedding_similarity(["a", "b", "c"], br)
        assert result["mean"] == pytest.approx(1.0)
        assert result["std"] == pytest.approx(0.0)

    def test_orthogonal_embeddings_give_similarity_zero(self):
        br = _embedding_mock([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        result = compute_embedding_similarity(["a", "b", "c"], br)
        assert result["mean"] == pytest.approx(0.0)

    def test_output_dict_keys(self):
        vec = [1.0, 0.0]
        br = _embedding_mock([vec, vec, vec])
        result = compute_embedding_similarity(["a", "b", "c"], br)
        assert set(result.keys()) == {"n_runs", "n_pairs", "mean", "min", "max", "std", "variance", "cv"}

    def test_return_is_pure_python(self):
        vec = [0.5, 0.5]
        br = _embedding_mock([vec, vec, vec])
        result = compute_embedding_similarity(["a", "b", "c"], br)
        for key, val in result.items():
            if val is not None:
                assert type(val) in (int, float), f"{key} returned {type(val)}"

    def test_dissimilar_embedding_lowers_min(self):
        br = _embedding_mock([
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],   # same as first — high similarity pair
            [0.0, 0.0, 1.0],   # orthogonal — low similarity with both
        ])
        result = compute_embedding_similarity(["a", "b", "c"], br)
        assert result["min"] < result["mean"]

    def test_invoke_model_called_once_per_text(self):
        vec = [1.0, 0.0]
        br = _embedding_mock([vec] * 4)
        compute_embedding_similarity(["w", "x", "y", "z"], br)
        assert br.invoke_model.call_count == 4


# ── TestMultiRunOrchestration ──────────────────────────────────────────────────


class TestMultiRunOrchestration:
    """Validates run_evaluation() orchestration with Bedrock and metric functions mocked."""

    _STUB_STATS = {
        "n_runs": 3, "n_pairs": 3, "mean": 0.9, "min": 0.8,
        "max": 1.0, "std": 0.05, "variance": 0.0025, "cv": 0.055,
    }

    @staticmethod
    def _tool_use_response(data: dict) -> dict:
        return {
            "output": {
                "message": {
                    "content": [{"toolUse": {"name": "extract_document", "input": data}}]
                }
            },
            "usage": {"inputTokens": 100, "outputTokens": 50},
        }

    @contextlib.contextmanager
    def _run_context(self, tmp_path, monkeypatch, *, n_runs: int = 3, temperature: float = 0.7):
        """Sets up all mocks needed by run_evaluation() and yields (args, bedrock_mock)."""
        doc = tmp_path / "doc.txt"
        doc.write_text("Patient has elevated glucose.")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Extract data from this medical document.")

        schema = {
            "type": "object",
            "properties": {"glucose": {"type": "number"}},
            "required": ["glucose"],
        }
        monkeypatch.setattr(_mod, "_load_schema", lambda _dt: schema)

        tdir = tmp_path / "templates"
        tdir.mkdir(exist_ok=True)
        (tdir / "lab_result.j2").write_text("Glucose: {{ glucose }}")
        monkeypatch.setattr(_mod, "TEMPLATE_DIR", tdir)

        bedrock_mock = mock.MagicMock()
        bedrock_mock.converse.side_effect = [
            self._tool_use_response({"glucose": round(5.5 + i * 0.1, 2)}) for i in range(n_runs)
        ]

        args = mock.MagicMock()
        args.document = str(doc)
        args.prompt = str(prompt)
        args.doc_type = "lab_result"
        args.model_id = "us.anthropic.claude-test-v1:0"
        args.n_runs = n_runs
        args.temperature = temperature
        args.region = "us-east-1"
        args.output_json = None

        stub = {**self._STUB_STATS, "n_runs": n_runs}

        with mock.patch.object(_mod, "compute_embedding_similarity", return_value=stub), \
             mock.patch.object(_mod, "compute_tfidf_similarity", return_value=stub), \
             mock.patch("boto3.client", return_value=bedrock_mock):
            yield args, bedrock_mock

    def test_n_calls_made_to_bedrock(self, tmp_path, monkeypatch):
        with self._run_context(tmp_path, monkeypatch, n_runs=3) as (args, bedrock_mock):
            run_evaluation(args)
        assert bedrock_mock.converse.call_count == 3

    def test_temperature_override_in_all_calls(self, tmp_path, monkeypatch):
        with self._run_context(tmp_path, monkeypatch, n_runs=2, temperature=0.7) as (args, bedrock_mock):
            run_evaluation(args)
        for call in bedrock_mock.converse.call_args_list:
            assert call.kwargs["inferenceConfig"]["temperature"] == pytest.approx(0.7)

    def test_result_includes_both_layers(self, tmp_path, monkeypatch):
        with self._run_context(tmp_path, monkeypatch) as (args, _):
            result = run_evaluation(args)
        assert "text_layer" in result
        assert "json_layer" in result

    def test_result_includes_all_metric_keys(self, tmp_path, monkeypatch):
        with self._run_context(tmp_path, monkeypatch) as (args, _):
            result = run_evaluation(args)
        assert set(result["text_layer"].keys()) == {"embedding_cosine", "tfidf_cosine"}
