"""Unit tests for the classifier Lambda handler."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

CLASSIFIER_DIR = Path(__file__).parent.parent / 'lambda' / 'classifier'
sys.path.insert(0, str(CLASSIFIER_DIR))

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


def make_converse_response(label):
    return {
        'output': {
            'message': {
                'content': [{'text': label}]
            }
        }
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
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.bedrock_runtime') as mock_runtime, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response(label)
            mock_s3.get_object.return_value = make_s3_response()

            import handler
            result = handler.lambda_handler(
                {'job_id': 'job-1', 'bucket': 'test-bucket', 'key': 'uploads/job-1/doc.txt'},
                None,
            )

        assert result['doc_type'] == label
        assert result['job_id'] == 'job-1'

    def test_label_stripped_and_lowercased(self):
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.bedrock_runtime') as mock_runtime, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('  Lab_Result  ')
            mock_s3.get_object.return_value = make_s3_response()

            import handler
            with pytest.raises(ValueError, match='unknown doc type'):
                handler.lambda_handler(
                    {'job_id': 'job-1', 'bucket': 'b', 'key': 'uploads/job-1/doc.txt'},
                    None,
                )


class TestClassifierErrorHandling:
    def test_unknown_label_raises_value_error(self):
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.bedrock_runtime') as mock_runtime, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('financial_report')
            mock_s3.get_object.return_value = make_s3_response()

            import handler
            with pytest.raises(ValueError, match='unknown doc type'):
                handler.lambda_handler(
                    {'job_id': 'job-2', 'bucket': 'b', 'key': 'uploads/job-2/doc.txt'},
                    None,
                )

    def test_bedrock_throttle_propagates(self):
        from botocore.exceptions import ClientError
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.bedrock_runtime') as mock_runtime, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_s3.get_object.return_value = make_s3_response()
            mock_runtime.converse.side_effect = ClientError(
                {'Error': {'Code': 'ThrottlingException', 'Message': 'Rate exceeded'}},
                'Converse',
            )

            import handler
            with pytest.raises(ClientError):
                handler.lambda_handler(
                    {'job_id': 'job-3', 'bucket': 'b', 'key': 'uploads/job-3/doc.txt'},
                    None,
                )

    def test_empty_prompt_variants_raises(self):
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = {'variants': []}
            mock_s3.get_object.return_value = make_s3_response()

            import handler
            with pytest.raises(ValueError, match='No variants'):
                handler.lambda_handler(
                    {'job_id': 'job-4', 'bucket': 'b', 'key': 'uploads/job-4/doc.txt'},
                    None,
                )


class TestClassifierPromptRetrieval:
    def test_get_prompt_called_with_arn_and_version(self):
        with mock.patch('handler.bedrock_agent') as mock_agent, \
             mock.patch('handler.bedrock_runtime') as mock_runtime, \
             mock.patch('handler.s3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_converse_response('lab_result')
            mock_s3.get_object.return_value = make_s3_response()

            import handler
            handler.lambda_handler(
                {'job_id': 'job-5', 'bucket': 'b', 'key': 'uploads/job-5/doc.txt'},
                None,
            )

            mock_agent.get_prompt.assert_called_once_with(
                promptIdentifier=MOCK_ENV['CLASSIFIER_PROMPT_ARN'],
                promptVersion=MOCK_ENV['CLASSIFIER_PROMPT_VERSION'],
            )
