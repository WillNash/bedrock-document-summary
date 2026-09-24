"""Unit tests for the classifier Lambda handler."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

CLASSIFIER_DIR = Path(__file__).parent.parent / 'lambda' / 'classifier'

MOCK_ENV = {
    'CLASSIFIER_PROMPT_ARN': 'arn:aws:bedrock:us-east-1:123456789:prompt/abc123',
    'CLASSIFIER_PROMPT_VERSION': '1',
    'BEDROCK_CLASSIFIER_MODEL_ID': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    'JOBS_TABLE': 'test-jobs',
}

MOCK_PROMPT_RESPONSE = {
    'variants': [
        {
            'templateConfiguration': {
                'text': {'text': 'Classify this medical document into one of the following types...'}
            }
        }
    ]
}

_spec = importlib.util.spec_from_file_location('classifier_handler', CLASSIFIER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def make_converse_response(label, input_tokens=100, output_tokens=5):
    return {
        'output': {
            'message': {
                'content': [{'text': label}]
            }
        },
        'usage': {'inputTokens': input_tokens, 'outputTokens': output_tokens, 'totalTokens': input_tokens + output_tokens},
    }


def make_s3_response(text='Patient: John Doe\nLab results: CBC...'):
    body_mock = mock.MagicMock()
    body_mock.read.return_value = text.encode('utf-8')
    return {'Body': body_mock}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestClassifierLabels:
    @pytest.mark.parametrize('label', [
        'lab_result',
        'doctors_notes',
        'injury_doc',
        'visit_assessment',
        'psych_eval',
    ])
    def test_all_valid_labels_parsed(self, label):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response(label)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'job-1', 'bucket': 'test-bucket', 'key': 'uploads/job-1/doc.txt'},
                None,
            )

        assert result['doc_type'] == label
        assert result['job_id'] == 'job-1'
        assert result['usage_stats']['classifier']['input_tokens'] == 100
        assert result['usage_stats']['classifier']['output_tokens'] == 5
        assert result['usage_stats']['classifier']['model'] == MOCK_ENV['BEDROCK_CLASSIFIER_MODEL_ID']

    def test_whitespace_padded_label_accepted(self):
        """Handler strips and lowercases before matching — padded labels are accepted."""
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('  Lab_Result  ')
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'job-1', 'bucket': 'b', 'key': 'uploads/job-1/doc.txt'},
                None,
            )

        assert result['doc_type'] == 'lab_result'


class TestClassifierErrorHandling:
    def test_unknown_label_raises_value_error(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('financial_report')
            mock_s3.get_object.return_value = make_s3_response()

            with pytest.raises(ValueError, match='unknown doc type'):
                handler.lambda_handler(
                    {'job_id': 'job-2', 'bucket': 'b', 'key': 'uploads/job-2/doc.txt'},
                    None,
                )

    def test_bedrock_throttle_propagates(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_s3.get_object.return_value = make_s3_response()
            mock_runtime.converse.side_effect = ClientError(
                {'Error': {'Code': 'ThrottlingException', 'Message': 'Rate exceeded'}},
                'Converse',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(
                    {'job_id': 'job-3', 'bucket': 'b', 'key': 'uploads/job-3/doc.txt'},
                    None,
                )

    def test_empty_prompt_variants_raises(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = {'variants': []}
            mock_s3.get_object.return_value = make_s3_response()

            with pytest.raises(ValueError, match='No variants'):
                handler.lambda_handler(
                    {'job_id': 'job-4', 'bucket': 'b', 'key': 'uploads/job-4/doc.txt'},
                    None,
                )


class TestDocTypeBypass:
    def test_preset_doc_type_skips_bedrock_and_s3(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            result = handler.lambda_handler(
                {
                    'job_id': 'job-bypass',
                    'bucket': 'test-bucket',
                    'key': 'uploads/job-bypass/doc.txt',
                    'doc_type': 'lab_result',
                },
                None,
            )

        mock_s3.get_object.assert_not_called()
        mock_runtime.converse.assert_not_called()
        mock_agent.get_prompt.assert_not_called()
        assert result['doc_type'] == 'lab_result'
        assert result['usage_stats'] == {}

    def test_preset_doc_type_passes_validate_flag(self):
        with mock.patch.object(handler, 'bedrock_agent'), \
             mock.patch.object(handler, 'bedrock_runtime'), \
             mock.patch.object(handler, 's3_client'):

            result = handler.lambda_handler(
                {
                    'job_id': 'job-bypass',
                    'bucket': 'b',
                    'key': 'uploads/job-bypass/doc.txt',
                    'doc_type': 'doctors_notes',
                    'validate': True,
                },
                None,
            )

        assert result['validate'] is True

    def test_preset_doc_type_passes_custom_prompt(self):
        with mock.patch.object(handler, 'bedrock_agent'), \
             mock.patch.object(handler, 'bedrock_runtime'), \
             mock.patch.object(handler, 's3_client'):

            result = handler.lambda_handler(
                {
                    'job_id': 'job-bypass',
                    'bucket': 'b',
                    'key': 'uploads/job-bypass/doc.txt',
                    'doc_type': 'injury_doc',
                    'custom_prompt': 'Extract everything carefully.',
                },
                None,
            )

        assert result['custom_prompt'] == 'Extract everything carefully.'
        assert 'custom_schema' not in result

    def test_preset_doc_type_passes_custom_schema_including_empty_string(self):
        with mock.patch.object(handler, 'bedrock_agent'), \
             mock.patch.object(handler, 'bedrock_runtime'), \
             mock.patch.object(handler, 's3_client'):

            result = handler.lambda_handler(
                {
                    'job_id': 'job-bypass',
                    'bucket': 'b',
                    'key': 'uploads/job-bypass/doc.txt',
                    'doc_type': 'injury_doc',
                    'custom_schema': '',
                },
                None,
            )

        assert result['custom_schema'] == ''

    def test_validate_flag_passed_through_normal_path(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('lab_result')
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {
                    'job_id': 'job-normal',
                    'bucket': 'b',
                    'key': 'uploads/job-normal/doc.txt',
                    'validate': True,
                },
                None,
            )

        assert result['validate'] is True

    def test_validate_defaults_to_false_on_normal_path(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('lab_result')
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'job-normal', 'bucket': 'b', 'key': 'uploads/job-normal/doc.txt'},
                None,
            )

        assert result['validate'] is False


class TestClassifierPromptRetrieval:
    def test_get_prompt_called_with_arn_and_version(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('lab_result')
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {'job_id': 'job-5', 'bucket': 'b', 'key': 'uploads/job-5/doc.txt'},
                None,
            )

            mock_agent.get_prompt.assert_called_once_with(
                promptIdentifier=MOCK_ENV['CLASSIFIER_PROMPT_ARN'],
                promptVersion=MOCK_ENV['CLASSIFIER_PROMPT_VERSION'],
            )
