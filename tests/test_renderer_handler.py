"""Unit tests for the renderer Lambda handler (S3 and DynamoDB integration)."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'renderer'
TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'

MOCK_ENV = {
    'SUMMARIES_BUCKET': 'test-summaries',
    'JOBS_TABLE': 'test-jobs',
    'EXPERIMENTS_TABLE': 'test-experiments',
    'COMPARISON_SM_ARN': 'arn:aws:states:us-east-1:123456789:stateMachine:test-comparison',
}

_spec = importlib.util.spec_from_file_location('renderer_handler', HANDLER_DIR / 'handler.py')
renderer_handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(renderer_handler)

SAMPLE_EVENT = {
    'job_id': 'job-rdr-1',
    'doc_type': 'lab_result',
    'validated_data': {
        'patient_id': 'P-001',
        'test_date': '2025-01-15',
        'ordering_provider': 'Dr. Smith',
        'test_panels': [
            {
                'panel_name': 'CBC',
                'results': [
                    {'name': 'Hgb', 'value': '13.5', 'unit': 'g/dL', 'reference_range': '12-16', 'flag': None},
                ],
            }
        ],
        'interpretation': None,
        'notes': None,
    },
    'usage_stats': {
        'classifier': {'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0', 'input_tokens': 100, 'output_tokens': 5},
        'extractor': {'model': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0', 'input_tokens': 2000, 'output_tokens': 300},
    },
}

CLAIM_STATS = {'total': 5, 'supported': 4, 'contradicted': 1, 'unverifiable': 0}

VALIDATED_EXPERIMENT_EVENT = {
    **{
        'job_id': 'job-rdr-2',
        'doc_type': 'lab_result',
        'bucket': 'test-uploads',
        'key': 'uploads/job-rdr-2/doc.txt',
        'experiment_id': 'exp-001',
        'run_number': 1,
        'validated_data': SAMPLE_EVENT['validated_data'],
        'usage_stats': {
            'classifier': {
                'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
                'prompt_arn': 'arn:aws:bedrock:us-east-1:123:prompt/abc',
                'prompt_version': '1',
                'guardrail_id': 'gr-123',
                'guardrail_version': '1',
                'input_tokens': 100,
                'output_tokens': 5,
            },
            'extractor': {
                'model': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
                'prompt_arn': 'arn:aws:bedrock:us-east-1:123:prompt/def',
                'prompt_version': '2',
                'input_tokens': 2000,
                'output_tokens': 300,
            },
        },
    },
    'claim_validation': {
        'output': {
            'validated_summary_key': 'summaries/job-rdr-2/validated_summary.txt',
            'claim_stats': CLAIM_STATS,
        },
    },
}

EXPERIMENT_EVENT = {
    **SAMPLE_EVENT,
    'job_id': 'job-rdr-2',
    'bucket': 'test-uploads',
    'key': 'uploads/job-rdr-2/doc.txt',
    'experiment_id': 'exp-001',
    'run_number': 1,
    'usage_stats': {
        'classifier': {
            'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
            'prompt_arn': 'arn:aws:bedrock:us-east-1:123:prompt/abc',
            'prompt_version': '1',
            'guardrail_id': 'gr-123',
            'guardrail_version': '1',
            'input_tokens': 100,
            'output_tokens': 5,
        },
        'extractor': {
            'model': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
            'prompt_arn': 'arn:aws:bedrock:us-east-1:123:prompt/def',
            'prompt_version': '2',
            'input_tokens': 2000,
            'output_tokens': 300,
        },
    },
}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def patch_templates(monkeypatch):
    real_env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    monkeypatch.setattr(renderer_handler, 'jinja_env', real_env)


class TestRendererHandler:
    def test_s3_put_object_called_with_correct_key(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            assert 'summaries/job-rdr-1/summary.txt' in put_calls
            assert put_calls['summaries/job-rdr-1/summary.txt']['Bucket'] == 'test-summaries'
            assert put_calls['summaries/job-rdr-1/summary.txt']['ContentType'] == 'text/plain; charset=utf-8'

    def test_usage_json_written_to_s3(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            assert 'summaries/job-rdr-1/usage.json' in put_calls
            usage_body = json.loads(put_calls['summaries/job-rdr-1/usage.json']['Body'])
            assert usage_body['classifier']['input_tokens'] == 100
            assert usage_body['extractor']['output_tokens'] == 300

    def test_summary_body_contains_patient_data(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            summary_body = put_calls['summaries/job-rdr-1/summary.txt']['Body']
            assert b'P-001' in summary_body

    def test_dynamodb_updated_to_completed(self):
        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            mock_table.update_item.assert_called_once()
            call_kwargs = mock_table.update_item.call_args[1]
            assert call_kwargs['ExpressionAttributeValues'][':s'] == 'COMPLETED'
            assert call_kwargs['ExpressionAttributeValues'][':dt'] == 'lab_result'

    def test_return_value_includes_summary_key(self):
        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            result = renderer_handler.lambda_handler(SAMPLE_EVENT, None)

        assert result['job_id'] == 'job-rdr-1'
        assert result['summary_key'] == 'summaries/job-rdr-1/summary.txt'


class TestRendererExperimentOutputs:
    def _make_ddb_mock(self, completed_n=1, expected_n=5, successful_n=1):
        from decimal import Decimal
        mock_ddb = mock.MagicMock()
        mock_table = mock.MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_table.update_item.return_value = {
            'Attributes': {
                'completed_n': Decimal(str(completed_n)),
                'expected_n': Decimal(str(expected_n)),
                'successful_n': Decimal(str(successful_n)),
            }
        }
        return mock_ddb, mock_table

    def test_experiment_run_writes_to_experiment_prefix(self):
        mock_ddb, mock_table = self._make_ddb_mock()

        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client'):

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        put_calls = {c.kwargs['Key'] for c in mock_s3.put_object.call_args_list}
        assert 'experiments/exp-001/runs/1/summary.txt' in put_calls
        assert 'experiments/exp-001/runs/1/metadata.json' in put_calls

    def test_metadata_json_contains_provenance(self):
        mock_ddb, mock_table = self._make_ddb_mock()

        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client'):

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
        metadata = json.loads(put_calls['experiments/exp-001/runs/1/metadata.json']['Body'])
        assert metadata['experiment_id'] == 'exp-001'
        assert metadata['run_number'] == 1
        assert metadata['doc_type'] == 'lab_result'
        assert metadata['classification']['model_id'] == 'us.anthropic.claude-haiku-4-5-20251001-v1:0'
        assert metadata['extraction']['prompt_arn'] == 'arn:aws:bedrock:us-east-1:123:prompt/def'

    def test_comparison_sm_started_when_all_runs_complete(self):
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=5, expected_n=5, successful_n=5)

        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client') as mock_sfn:

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        mock_sfn.start_execution.assert_called_once()
        call_kwargs = mock_sfn.start_execution.call_args[1]
        assert call_kwargs['name'] == 'exp-001'

    def test_comparison_sm_not_started_when_runs_incomplete(self):
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=1, expected_n=5, successful_n=1)

        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client') as mock_sfn:

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        mock_sfn.start_execution.assert_not_called()

    def test_comparison_sm_started_when_completed_n_exceeds_expected(self):
        # completed_n can exceed expected_n when fail_handler double-increments on the
        # final run (renderer increments, then StartExecution fails, then fail_handler
        # also increments). The >= guard ensures the SM is still triggered.
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=6, expected_n=5, successful_n=5)

        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client') as mock_sfn:

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        mock_sfn.start_execution.assert_called_once()

    def test_claim_artifacts_written_to_experiment_prefix(self):
        mock_ddb, _ = self._make_ddb_mock()

        def get_object_side_effect(Bucket, Key):
            if Key == 'summaries/job-rdr-2/validated_summary.txt':
                return {'Body': mock.MagicMock(read=lambda: b'Validated summary.')}
            return {'Body': mock.MagicMock(read=lambda: b'artifact content')}

        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_s3.get_object.side_effect = get_object_side_effect
            renderer_handler.lambda_handler(VALIDATED_EXPERIMENT_EVENT, None)

        put_keys = {c.kwargs['Key'] for c in mock_s3.put_object.call_args_list}
        assert 'experiments/exp-001/runs/1/pre_render.txt' in put_keys
        assert 'experiments/exp-001/runs/1/claims.json' in put_keys
        assert 'experiments/exp-001/runs/1/triage.json' in put_keys
        assert 'experiments/exp-001/runs/1/verdicts.json' in put_keys

    def test_claim_stats_written_to_metadata(self):
        mock_ddb, _ = self._make_ddb_mock()

        def get_object_side_effect(Bucket, Key):
            if Key == 'summaries/job-rdr-2/validated_summary.txt':
                return {'Body': mock.MagicMock(read=lambda: b'Validated summary.')}
            return {'Body': mock.MagicMock(read=lambda: b'{}')}

        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client'):

            mock_s3.get_object.side_effect = get_object_side_effect
            renderer_handler.lambda_handler(VALIDATED_EXPERIMENT_EVENT, None)

        put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
        metadata = json.loads(put_calls['experiments/exp-001/runs/1/metadata.json']['Body'])
        assert 'claim_validation' in metadata
        assert metadata['claim_validation']['stats'] == CLAIM_STATS

    def test_non_validated_experiment_omits_claim_artifacts(self):
        mock_ddb, _ = self._make_ddb_mock()

        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb', mock_ddb), \
             mock.patch.object(renderer_handler, 'sfn_client'):

            renderer_handler.lambda_handler(EXPERIMENT_EVENT, None)

        put_keys = {c.kwargs['Key'] for c in mock_s3.put_object.call_args_list}
        assert not any('claims' in k or 'triage' in k or 'verdicts' in k or 'pre_render' in k
                       for k in put_keys)
        metadata_body = next(
            c.kwargs['Body'] for c in mock_s3.put_object.call_args_list
            if c.kwargs['Key'] == 'experiments/exp-001/runs/1/metadata.json'
        )
        assert 'claim_validation' not in json.loads(metadata_body)

    def test_non_experiment_job_skips_experiment_path(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(renderer_handler, 'sfn_client') as mock_sfn:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

        mock_sfn.start_execution.assert_not_called()
        put_keys = {c.kwargs['Key'] for c in mock_s3.put_object.call_args_list}
        assert not any('experiments/' in k for k in put_keys)
