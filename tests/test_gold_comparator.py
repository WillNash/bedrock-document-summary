"""
Tests for lambda/gold_comparator/handler.py.

All Bedrock invoke_model calls are mocked — no AWS credentials needed.
The mock is keyed by inputText content (not call order) because the handler
uses ThreadPoolExecutor and call order is non-deterministic.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

# ── Load handler ──────────────────────────────────────────────────────────────

_LAMBDA_DIR = Path(__file__).parent.parent / "lambda" / "gold_comparator"
_spec = importlib.util.spec_from_file_location("gold_comparator_handler", _LAMBDA_DIR / "handler.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["gold_comparator_handler"] = _mod
try:
    _spec.loader.exec_module(_mod)
except ImportError as _e:
    pytest.skip(f"gold_comparator handler import failed: {_e}", allow_module_level=True)

lambda_handler = _mod.lambda_handler


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_response(vec):
    body = json.dumps({"embedding": vec}).encode()
    return {"body": io.BytesIO(body)}


def _bedrock_mock(input_text_to_vec):
    client = mock.MagicMock()

    def _side_effect(*args, **kwargs):
        body_bytes = kwargs.get("body") or (args[1] if len(args) > 1 else b"{}")
        input_text = json.loads(body_bytes)["inputText"]
        return _make_response(input_text_to_vec[input_text])

    client.invoke_model.side_effect = _side_effect
    return client


def _event(texts, reference):
    return {"body": json.dumps({"texts": texts, "reference": reference})}


def _call(texts, reference, vec_map):
    client = _bedrock_mock(vec_map)
    with mock.patch("boto3.client", return_value=client):
        response = lambda_handler(_event(texts, reference), None)
    return response, client, json.loads(response["body"])


# ── Sample data ───────────────────────────────────────────────────────────────

_TEXTS = [
    "patient blood glucose elevated hemoglobin levels",
    "blood glucose high in this patient hemoglobin",
    "doctor visit prescription medicine normal refill",
]
_REF = "patient has elevated blood glucose and hemoglobin results"

_VEC_A = [1.0, 0.0, 0.0]
_VEC_B = [0.0, 1.0, 0.0]
_VEC_C = [0.0, 0.0, 1.0]


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_texts_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": json.dumps({"reference": _REF})}, None)
        assert resp["statusCode"] == 400

    def test_missing_reference_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": json.dumps({"texts": _TEXTS})}, None)
        assert resp["statusCode"] == 400

    def test_empty_reference_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler(_event(_TEXTS, "   "), None)
        assert resp["statusCode"] == 400

    def test_single_text_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler(_event(["only one"], _REF), None)
        assert resp["statusCode"] == 400

    def test_above_max_texts_returns_400(self):
        texts = [f"text {i}" for i in range(201)]
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler(_event(texts, _REF), None)
        assert resp["statusCode"] == 400

    def test_non_string_text_entry_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": json.dumps({"texts": ["ok", 42], "reference": _REF})}, None)
        assert resp["statusCode"] == 400

    def test_invalid_json_returns_400(self):
        with mock.patch("boto3.client", return_value=mock.MagicMock()):
            resp = lambda_handler({"body": "not json"}, None)
        assert resp["statusCode"] == 400


# ── Response structure ────────────────────────────────────────────────────────


class TestResponseStructure:
    def _simple_vec_map(self, texts, ref):
        vec = [1.0, 0.0, 0.0]
        return {t: vec for t in texts + [ref]}

    def test_200_for_valid_input(self):
        vec_map = self._simple_vec_map(_TEXTS[:2], _REF)
        resp, _, _ = _call(_TEXTS[:2], _REF, vec_map)
        assert resp["statusCode"] == 200

    def test_top_level_keys(self):
        vec_map = self._simple_vec_map(_TEXTS[:2], _REF)
        _, _, body = _call(_TEXTS[:2], _REF, vec_map)
        assert set(body.keys()) == {"embedding_cosine", "rouge1"}

    def test_tfidf_not_in_response(self):
        vec_map = self._simple_vec_map(_TEXTS[:2], _REF)
        _, _, body = _call(_TEXTS[:2], _REF, vec_map)
        assert "tfidf_cosine" not in body

    def test_stats_keys_in_each_metric(self):
        vec_map = self._simple_vec_map(_TEXTS[:2], _REF)
        _, _, body = _call(_TEXTS[:2], _REF, vec_map)
        expected = {"scores", "mean", "min", "max", "std", "n"}
        assert set(body["embedding_cosine"].keys()) == expected
        assert set(body["rouge1"].keys()) == expected

    def test_scores_length_matches_texts_count(self):
        vec_map = self._simple_vec_map(_TEXTS, _REF)
        _, _, body = _call(_TEXTS, _REF, vec_map)
        assert len(body["embedding_cosine"]["scores"]) == len(_TEXTS)
        assert len(body["rouge1"]["scores"]) == len(_TEXTS)

    def test_n_matches_texts_count(self):
        vec_map = self._simple_vec_map(_TEXTS, _REF)
        _, _, body = _call(_TEXTS, _REF, vec_map)
        assert body["embedding_cosine"]["n"] == len(_TEXTS)
        assert body["rouge1"]["n"] == len(_TEXTS)


# ── Metric correctness ────────────────────────────────────────────────────────


class TestMetricCorrectness:
    def test_identical_embedding_gives_score_one(self):
        vec = [1.0, 0.0, 0.0]
        vec_map = {t: vec for t in _TEXTS[:3] + [_REF]}
        _, _, body = _call(_TEXTS[:3], _REF, vec_map)
        for score in body["embedding_cosine"]["scores"]:
            assert score == pytest.approx(1.0)

    def test_orthogonal_embedding_gives_score_zero(self):
        ref_vec = [1.0, 0.0, 0.0]
        text_vec = [0.0, 1.0, 0.0]
        vec_map = {t: text_vec for t in _TEXTS[:3]}
        vec_map[_REF] = ref_vec
        _, _, body = _call(_TEXTS[:3], _REF, vec_map)
        for score in body["embedding_cosine"]["scores"]:
            assert score == pytest.approx(0.0)

    def test_rouge1_identical_texts_score_one(self):
        text = "the patient has elevated glucose levels"
        vec = [1.0, 0.0]
        vec_map = {text: vec}
        event = {"body": json.dumps({"texts": [text, text], "reference": text})}
        client = _bedrock_mock(vec_map)
        with mock.patch("boto3.client", return_value=client):
            response = lambda_handler(event, None)
        body = json.loads(response["body"])
        for score in body["rouge1"]["scores"]:
            assert score == pytest.approx(1.0)

    def test_rouge1_disjoint_texts_score_zero(self):
        reference = "apple banana cherry"
        t1 = "cat dog elephant fox"
        t2 = "wolf bear tiger lion"
        vec = [1.0, 0.0]
        vec_map = {t1: vec, t2: vec, reference: vec}
        _, _, body = _call([t1, t2], reference, vec_map)
        for score in body["rouge1"]["scores"]:
            assert score == pytest.approx(0.0)

    def test_invoke_model_called_n_plus_one_times(self):
        n = 3
        vec = [1.0, 0.0]
        vec_map = {t: vec for t in _TEXTS[:n] + [_REF]}
        _, client, _ = _call(_TEXTS[:n], _REF, vec_map)
        assert client.invoke_model.call_count == n + 1

    def test_all_values_are_plain_python_types(self):
        vec = [0.5, 0.5]
        vec_map = {t: vec for t in _TEXTS[:2] + [_REF]}
        _, _, body = _call(_TEXTS[:2], _REF, vec_map)
        for metric in ("embedding_cosine", "rouge1"):
            for key, val in body[metric].items():
                if key in ("scores", "n"):
                    continue
                assert type(val) in (int, float), f"{metric}.{key} returned {type(val)}"

    def test_mean_is_average_of_scores(self):
        vec = [0.6, 0.8]
        vec_map = {t: vec for t in _TEXTS[:3] + [_REF]}
        _, _, body = _call(_TEXTS[:3], _REF, vec_map)
        for metric in ("embedding_cosine", "rouge1"):
            scores = body[metric]["scores"]
            expected_mean = sum(scores) / len(scores)
            assert body[metric]["mean"] == pytest.approx(expected_mean)
