"""Unit tests for the extractor Lambda handler."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock

import pytest

EXTRACTOR_DIR = Path(__file__).parent.parent / 'lambda' / 'extractor'
SCHEMAS_DIR = Path(__file__).parent.parent / 'schemas'

PROMPT_ARNS = {
    'lab_result': 'arn:aws:bedrock:us-east-1:123456789:prompt/lab',
    'doctors_notes': 'arn:aws:bedrock:us-east-1:123456789:prompt/notes',
    'injury_doc': 'arn:aws:bedrock:us-east-1:123456789:prompt/injury',
    'visit_assessment': 'arn:aws:bedrock:us-east-1:123456789:prompt/visit',
    'psych_eval': 'arn:aws:bedrock:us-east-1:123456789:prompt/psych',
}
PROMPT_VERSIONS = {k: '1' for k in PROMPT_ARNS}

MOCK_ENV = {
    'BEDROCK_MODEL_ID': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
    'PROMPT_ARNS_JSON': json.dumps(PROMPT_ARNS),
    'PROMPT_VERSIONS_JSON': json.dumps(PROMPT_VERSIONS),
    'JOBS_TABLE': 'test-jobs',
}

MOCK_PROMPT_RESPONSE = {
    'variants': [
        {'templateConfiguration': {'text': {'text': 'Extract data from this lab result...'}}}
    ]
}

EXTRACTED_LAB_RESULT = {
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
}

_spec = importlib.util.spec_from_file_location('extractor_handler', EXTRACTOR_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def make_text_response(text='Free-form summary text.', input_tokens=2000, output_tokens=300):
    return {
        'output': {
            'message': {
                'content': [{'text': text}]
            }
        },
        'usage': {'inputTokens': input_tokens, 'outputTokens': output_tokens, 'totalTokens': input_tokens + output_tokens},
    }


def make_tool_use_response(tool_input, input_tokens=2000, output_tokens=300):
    return {
        'output': {
            'message': {
                'content': [
                    {
                        'toolUse': {
                            'toolUseId': 'tooluse-abc',
                            'name': 'extract_document',
                            'input': tool_input,
                        }
                    }
                ]
            }
        },
        'usage': {'inputTokens': input_tokens, 'outputTokens': output_tokens, 'totalTokens': input_tokens + output_tokens},
    }


def make_s3_response(text='Patient: John Doe\nLab: CBC results...'):
    body_mock = mock.MagicMock()
    body_mock.read.return_value = text.encode('utf-8')
    return {'Body': body_mock}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def patch_schema_dir(monkeypatch):
    monkeypatch.setattr(handler, 'SCHEMA_DIR', SCHEMAS_DIR)


class TestExtractorToolUseRequest:
    def test_tool_choice_is_forced(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {'job_id': 'j1', 'bucket': 'b', 'key': 'uploads/j1/doc.txt',
                 'doc_type': 'lab_result'},
                None,
            )

            call_kwargs = mock_runtime.converse.call_args.kwargs
            assert call_kwargs['toolConfig']['toolChoice'] == {'tool': {'name': 'extract_document'}}

    def test_tool_schema_matches_doc_type(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {'job_id': 'j2', 'bucket': 'b', 'key': 'uploads/j2/doc.txt',
                 'doc_type': 'lab_result'},
                None,
            )

            call_kwargs = mock_runtime.converse.call_args.kwargs
            tool_spec = call_kwargs['toolConfig']['tools'][0]['toolSpec']
            schema = tool_spec['inputSchema']['json']
            assert schema.get('title') == 'LabResult'

    @pytest.mark.parametrize('doc_type,expected_title', [
        ('lab_result', 'LabResult'),
        ('injury_doc', 'InjuryDoc'),
        ('doctors_notes', 'DoctorsNotes'),
        ('visit_assessment', 'VisitAssessment'),
        ('psych_eval', 'PsychEval'),
    ])
    def test_each_doc_type_selects_correct_schema(self, doc_type, expected_title):
        extracted = {'patient_id': 'P-001', 'eval_date': '2025-01-01',
                     'evaluator': 'Dr. X', 'presenting_concerns': 'Test',
                     'mental_status_summary': 'Normal', 'diagnostic_impressions': 'None',
                     'risk_assessment': None, 'recommendations': 'Follow up'}

        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(extracted)
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {'job_id': 'jx', 'bucket': 'b', 'key': f'uploads/jx/doc.txt',
                 'doc_type': doc_type},
                None,
            )

            call_kwargs = mock_runtime.converse.call_args.kwargs
            schema = call_kwargs['toolConfig']['tools'][0]['toolSpec']['inputSchema']['json']
            assert schema.get('title') == expected_title


class TestExtractorResponseParsing:
    def test_extracts_tool_use_input(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'j3', 'bucket': 'b', 'key': 'uploads/j3/doc.txt',
                 'doc_type': 'lab_result'},
                None,
            )

        assert result['extracted_data'] == EXTRACTED_LAB_RESULT

    def test_usage_stats_merged_with_upstream(self):
        upstream_usage = {'classifier': {'model': 'haiku', 'input_tokens': 100, 'output_tokens': 5}}
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT, input_tokens=2000, output_tokens=300)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'j-u', 'bucket': 'b', 'key': 'uploads/j-u/doc.txt',
                 'doc_type': 'lab_result', 'usage_stats': upstream_usage},
                None,
            )

        assert result['usage_stats']['classifier'] == upstream_usage['classifier']
        assert result['usage_stats']['extractor']['input_tokens'] == 2000
        assert result['usage_stats']['extractor']['output_tokens'] == 300
        assert result['usage_stats']['extractor']['model'] == MOCK_ENV['BEDROCK_MODEL_ID']

    def test_missing_tool_use_block_raises(self):
        bad_response = {
            'output': {
                'message': {
                    'content': [{'text': 'Here is the extracted data: ...'}]
                }
            }
        }

        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = bad_response
            mock_s3.get_object.return_value = make_s3_response()

            with pytest.raises(ValueError, match='toolUse block'):
                handler.lambda_handler(
                    {'job_id': 'j4', 'bucket': 'b', 'key': 'uploads/j4/doc.txt',
                     'doc_type': 'lab_result'},
                    None,
                )


class TestCustomPromptAndSchema:
    def test_custom_prompt_used_as_system_prompt(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {
                    'job_id': 'j-cp',
                    'bucket': 'b',
                    'key': 'uploads/j-cp/doc.txt',
                    'doc_type': 'lab_result',
                    'custom_prompt': 'My custom extraction prompt.',
                },
                None,
            )

        mock_agent.get_prompt.assert_not_called()
        call_kwargs = mock_runtime.converse.call_args.kwargs
        assert call_kwargs['system'] == [{'text': 'My custom extraction prompt.'}]

    def test_custom_schema_used_for_tool_spec(self):
        custom_schema = json.dumps({
            'type': 'object',
            'title': 'CustomDoc',
            'properties': {'field': {'type': 'string'}},
            'required': ['field'],
        })
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response({'field': 'value'})
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {
                    'job_id': 'j-cs',
                    'bucket': 'b',
                    'key': 'uploads/j-cs/doc.txt',
                    'doc_type': 'lab_result',
                    'custom_schema': custom_schema,
                },
                None,
            )

        call_kwargs = mock_runtime.converse.call_args.kwargs
        schema_used = call_kwargs['toolConfig']['tools'][0]['toolSpec']['inputSchema']['json']
        assert schema_used['title'] == 'CustomDoc'

    def test_custom_prompt_and_schema_passed_forward_in_return(self):
        custom_schema = json.dumps({'type': 'object', 'properties': {}})
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {
                    'job_id': 'j-fwd',
                    'bucket': 'b',
                    'key': 'uploads/j-fwd/doc.txt',
                    'doc_type': 'lab_result',
                    'custom_prompt': 'My prompt.',
                    'custom_schema': custom_schema,
                },
                None,
            )

        assert result['custom_prompt'] == 'My prompt.'
        assert result['custom_schema'] == custom_schema

    def test_custom_schema_empty_string_does_free_form_extraction(self):
        free_form_text = 'The patient had elevated WBC.'
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_text_response(free_form_text)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {
                    'job_id': 'j-es',
                    'bucket': 'b',
                    'key': 'uploads/j-es/doc.txt',
                    'doc_type': 'lab_result',
                    'custom_schema': '',
                },
                None,
            )

        call_kwargs = mock_runtime.converse.call_args.kwargs
        assert 'toolConfig' not in call_kwargs
        assert result['extracted_data'] == free_form_text
        assert result['custom_schema'] == ''

    def test_neither_field_in_return_when_not_in_event(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            result = handler.lambda_handler(
                {'job_id': 'j-none', 'bucket': 'b', 'key': 'uploads/j-none/doc.txt',
                 'doc_type': 'lab_result'},
                None,
            )

        assert 'custom_prompt' not in result
        assert 'custom_schema' not in result


class TestExtractorPromptRetrieval:
    def test_get_prompt_called_with_correct_arn_and_version(self):
        with mock.patch.object(handler, 'bedrock_agent') as mock_agent, \
             mock.patch.object(handler, 'bedrock_runtime') as mock_runtime, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_agent.get_prompt.return_value = MOCK_PROMPT_RESPONSE
            mock_runtime.converse.return_value = make_tool_use_response(EXTRACTED_LAB_RESULT)
            mock_s3.get_object.return_value = make_s3_response()

            handler.lambda_handler(
                {'job_id': 'j5', 'bucket': 'b', 'key': 'uploads/j5/doc.txt',
                 'doc_type': 'lab_result'},
                None,
            )

            mock_agent.get_prompt.assert_called_once_with(
                promptIdentifier=PROMPT_ARNS['lab_result'],
                promptVersion='1',
            )
