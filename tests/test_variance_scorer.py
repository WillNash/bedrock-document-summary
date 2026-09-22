"""Unit tests for the variance_scorer Lambda handler."""
import importlib.util
from pathlib import Path
from unittest import mock

import pytest

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'variance_scorer'

_spec = importlib.util.spec_from_file_location('variance_scorer_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

EVENT = {
    'summaries_bucket': 'test-summaries',
    'run_manifests': [
        {'run_number': 1, 'summary_key': 'experiments/exp-001/runs/1/summary.txt', 'metadata_key': '...'},
        {'run_number': 2, 'summary_key': 'experiments/exp-001/runs/2/summary.txt', 'metadata_key': '...'},
        {'run_number': 3, 'summary_key': 'experiments/exp-001/runs/3/summary.txt', 'metadata_key': '...'},
    ],
}

SAMPLE_TEXTS = [
    'Patient shows elevated white blood cell count.',
    'WBC is elevated. Patient has mild leukocytosis.',
    'Lab results show leukocytosis with elevated WBC.',
]

FAKE_EMBEDDING = [0.1] * 1024


def make_s3_mock(texts):
    mock_s3 = mock.MagicMock()
    responses = iter(texts)
    mock_s3.get_object.side_effect = lambda **kw: {
        'Body': mock.MagicMock(read=lambda: next(responses).encode())
    }
    return mock_s3


def make_bedrock_mock():
    import json
    mock_bedrock = mock.MagicMock()
    mock_bedrock.invoke_model.return_value = {
        'body': mock.MagicMock(read=lambda: json.dumps({'embedding': FAKE_EMBEDDING}).encode())
    }
    return mock_bedrock


class TestVarianceScorer:
    def test_returns_embedding_and_tfidf_stats(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        assert 'embedding_cosine' in result
        assert 'tfidf_cosine' in result

    def test_stats_include_expected_keys(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        for key in ('mean', 'std', 'min', 'max', 'variance', 'n_runs', 'n_pairs', 'matrix', 'run_numbers'):
            assert key in result['embedding_cosine'], f'Missing key: {key}'
            assert key in result['tfidf_cosine'], f'Missing key: {key}'

    def test_n_runs_and_n_pairs_correct(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        assert result['embedding_cosine']['n_runs'] == 3
        assert result['embedding_cosine']['n_pairs'] == 3  # C(3,2) = 3

    def test_matrix_dimensions_correct(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        matrix = result['embedding_cosine']['matrix']
        assert len(matrix) == 3
        assert all(len(row) == 3 for row in matrix)

    def test_diagonal_is_one(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        matrix = result['embedding_cosine']['matrix']
        assert all(abs(matrix[i][i] - 1.0) < 1e-9 for i in range(3))

    def test_fewer_than_2_runs_raises(self):
        event = {**EVENT, 'run_manifests': EVENT['run_manifests'][:1]}
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS[:1])), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            with pytest.raises(ValueError, match='at least 2'):
                handler.lambda_handler(event, None)

    def test_run_numbers_preserved_in_output(self):
        with mock.patch.object(handler, 's3_client', make_s3_mock(SAMPLE_TEXTS)), \
             mock.patch.object(handler, 'bedrock_client', make_bedrock_mock()):
            result = handler.lambda_handler(EVENT, None)

        assert result['embedding_cosine']['run_numbers'] == [1, 2, 3]
