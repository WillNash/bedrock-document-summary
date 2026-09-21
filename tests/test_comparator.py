"""
Tests for lambda/comparator/handler.py.

All Bedrock invoke_model calls are mocked — no AWS credentials needed.
"""

import importlib.util
import io
import json
from pathlib import Path
from unittest import mock

import pytest

# ── Load handler ──────────────────────────────────────────────────────────────

_LAMBDA_DIR = Path(__file__).parent.parent / "lambda" / "comparator"
_spec = importlib.util.spec_from_file_location("comparator_handler", _LAMBDA_DIR / "handler.py")
_mod = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_mod)
except ImportError as _e:
    pytest.skip(f"comparator handler import failed: {_e}", allow_module_level=True)

lambda_handler = _mod.lambda_handler


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bedrock_mock(vectors: list[list[float]]):
    client = mock.MagicMock()
    responses = []
    for vec in vectors:
        body = json.dumps({"embedding": vec, "inputTextTokenCount": len(vec)}).encode()
        responses.append({"body": io.BytesIO(body)})
    client.invoke_model.side_effect = responses
    return client


def _event(texts: list[str]) -> dict:
    return {"body": json.dumps({"texts": texts})}


def _call(texts: list[str], vectors: list[list[float]]):
    client = _bedrock_mock(vectors)
    with mock.patch("boto3.client", return_value=client):
        response = lambda_handler(_event(texts), None)
    return response, client, json.loads(response["body"])


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_body_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({}, None)
        assert resp["statusCode"] == 400

    def test_single_text_returns_400(self):
        client = _bedrock_mock([[1.0, 0.0]])
        with mock.patch("boto3.client", return_value=client):
            resp = lambda_handler(_event(["only one"]), None)
        assert resp["statusCode"] == 400

    def test_above_max_texts_returns_400(self):
        texts = [f"text {i}" for i in range(201)]
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler(_event(texts), None)
        assert resp["statusCode"] == 400

    def test_non_string_entry_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": json.dumps({"texts": ["ok", 42]})}, None)
        assert resp["statusCode"] == 400

    def test_invalid_json_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": "not json"}, None)
        assert resp["statusCode"] == 400


# ── Response structure ────────────────────────────────────────────────────────


_TEXTS = [
    "patient blood glucose elevated hemoglobin levels",
    "blood glucose high in this patient hemoglobin",
    "doctor visit prescription medicine normal refill",
    "patient elevated glucose lab result normal range",
]


class TestResponseStructure:
    def test_200_for_valid_input(self):
        vec = [1.0, 0.0, 0.0]
        resp, _, _ = _call(_TEXTS[:2], [vec, vec])
        assert resp["statusCode"] == 200

    def test_top_level_keys(self):
        vec = [1.0, 0.0]
        _, _, body = _call(_TEXTS[:2], [vec, vec])
        assert set(body.keys()) == {"embeddings", "embedding_cosine", "tfidf_cosine"}

    def test_stats_keys_in_each_metric(self):
        vec = [1.0, 0.0]
        _, _, body = _call(_TEXTS[:3], [vec, vec, vec])
        expected = {"n_runs", "n_pairs", "mean", "min", "max", "std", "variance", "cv", "matrix"}
        assert set(body["embedding_cosine"].keys()) == expected
        assert set(body["tfidf_cosine"].keys()) == expected

    def test_embeddings_count_matches_input(self):
        vecs = [[float(i), 0.0] for i in range(3)]
        _, _, body = _call(_TEXTS[:3], vecs)
        assert len(body["embeddings"]) == 3

    def test_embedding_vector_length(self):
        dim = 8
        vecs = [[0.1] * dim, [0.2] * dim]
        _, _, body = _call(_TEXTS[:2], vecs)
        assert all(len(v) == dim for v in body["embeddings"])

    def test_matrix_is_n_by_n(self):
        n = 4
        vecs = [[float(i), 0.0] for i in range(n)]
        _, _, body = _call(_TEXTS[:n], vecs)
        m = body["embedding_cosine"]["matrix"]
        assert len(m) == n
        assert all(len(row) == n for row in m)


# ── Metric correctness ────────────────────────────────────────────────────────


class TestMetricCorrectness:
    def test_identical_embeddings_mean_one(self):
        vec = [1.0, 0.0, 0.0, 0.0]
        _, _, body = _call(_TEXTS[:3], [vec, vec, vec])
        assert body["embedding_cosine"]["mean"] == pytest.approx(1.0)
        assert body["embedding_cosine"]["std"] == pytest.approx(0.0)

    def test_orthogonal_embeddings_mean_zero(self):
        vecs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        _, _, body = _call(_TEXTS[:3], vecs)
        assert body["embedding_cosine"]["mean"] == pytest.approx(0.0)

    def test_invoke_model_called_once_per_text(self):
        vecs = [[1.0, 0.0]] * 4
        _, client, _ = _call(_TEXTS[:4], vecs)
        assert client.invoke_model.call_count == 4

    def test_cv_is_none_when_mean_is_zero(self):
        vecs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        _, _, body = _call(_TEXTS[:3], vecs)
        assert body["embedding_cosine"]["cv"] is None

    def test_tfidf_identical_texts_high_similarity(self):
        text = "the patient has elevated glucose levels"
        vec = [1.0, 0.0]
        _, _, body = _call([text, text, text], [vec, vec, vec])
        assert body["tfidf_cosine"]["mean"] > 0.99

    def test_all_values_are_plain_python_types(self):
        vec = [0.5, 0.5]
        _, _, body = _call(_TEXTS[:3], [vec, vec, vec])
        for metric in ("embedding_cosine", "tfidf_cosine"):
            for key, val in body[metric].items():
                if key == "matrix":
                    continue
                if val is not None:
                    assert type(val) in (int, float), f"{metric}.{key} returned {type(val)}"
