"""Unit tests for the summary_assembler Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_PATH = Path(__file__).parent.parent / 'lambda' / 'summary_assembler' / 'handler.py'

_spec = importlib.util.spec_from_file_location('summary_assembler_handler', HANDLER_PATH)
summary_assembler_handler = importlib.util.module_from_spec(_spec)

with mock.patch.dict('os.environ', {
    'SUMMARIES_BUCKET': 'summaries-bucket',
    'EXPENSIVE_MODEL_ID': 'au.anthropic.claude-sonnet-test',
}):
    _spec.loader.exec_module(summary_assembler_handler)


BASE_EVENT = {
    'job_id': 'job-assemble-001',
    'bucket': 'upload-bucket',
    'key': 'uploads/job-assemble-001/doc.txt',
    'summary_key': 'summaries/job-assemble-001/pre_render.txt',
    'claims_key': 'summaries/job-assemble-001/claims.json',
    'triage_key': 'summaries/job-assemble-001/triage.json',
    'verdicts_key': 'summaries/job-assemble-001/verdicts.json',
}

ORIGINAL_SUMMARY = 'Patient had Hgb of 13.5 g/dL. Test was on 2025-01-15. CBC was normal.'

SUPPORTED_VERDICT = {'claim': 'Patient had Hgb of 13.5 g/dL.', 'verdict': 'supported', 'evidence_quote': 'Hgb 13.5', 'reason': 'matches'}
CONTRADICTED_VERDICT = {'claim': 'Test was on 2025-01-15.', 'verdict': 'contradicted', 'evidence_quote': 'Test date: 2025-01-20', 'reason': 'date mismatch'}
UNVERIFIABLE_VERDICT = {'claim': 'CBC was normal.', 'verdict': 'unverifiable', 'evidence_quote': '', 'reason': 'no passage found'}


def _make_s3_mock(verdicts):
    s3 = mock.MagicMock()

    def get_object_side_effect(Bucket, Key):
        if 'verdicts' in Key:
            return {'Body': mock.MagicMock(read=lambda: json.dumps(verdicts).encode())}
        if 'pre_render' in Key or 'summary' in Key:
            return {'Body': mock.MagicMock(read=lambda: ORIGINAL_SUMMARY.encode())}
        return {'Body': mock.MagicMock(read=lambda: b'')}

    s3.get_object.side_effect = get_object_side_effect
    return s3


def _make_bedrock_mock(response_text='Rewritten summary.'):
    bedrock = mock.MagicMock()
    bedrock.converse.return_value = {
        'output': {'message': {'content': [{'text': response_text}]}}
    }
    return bedrock


class TestSummaryAssembler:
    def test_full_regen_at_three_bad_claims(self):
        verdicts = [CONTRADICTED_VERDICT, CONTRADICTED_VERDICT, UNVERIFIABLE_VERDICT]
        bedrock = _make_bedrock_mock('Full regen summary.')
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 1
        prompt_used = bedrock.converse.call_args.kwargs['messages'][0]['content'][0]['text']
        assert 'Verified claims' in prompt_used
        assert ORIGINAL_SUMMARY in prompt_used

    def test_partial_repair_unverifiable_uses_hedging_prompt(self):
        verdicts = [SUPPORTED_VERDICT, UNVERIFIABLE_VERDICT]
        bedrock = _make_bedrock_mock('reportedly normal.')
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 1
        prompt_used = bedrock.converse.call_args.kwargs['messages'][0]['content'][0]['text']
        assert 'hedge' in prompt_used.lower() or 'reportedly' in prompt_used or 'the document states' in prompt_used
        assert 'evidence_quote' not in prompt_used

    def test_partial_repair_contradicted_uses_span_replacement_prompt(self):
        verdicts = [SUPPORTED_VERDICT, CONTRADICTED_VERDICT]
        bedrock = _make_bedrock_mock('Test was on 2025-01-20.')
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 1
        prompt_used = bedrock.converse.call_args.kwargs['messages'][0]['content'][0]['text']
        assert 'Test date: 2025-01-20' in prompt_used

    def test_mixed_partial_repair_calls_different_prompts(self):
        verdicts = [UNVERIFIABLE_VERDICT, CONTRADICTED_VERDICT]
        prompts_seen = []

        def capture_converse(**kwargs):
            prompts_seen.append(kwargs['messages'][0]['content'][0]['text'])
            return {'output': {'message': {'content': [{'text': 'rewritten'}]}}}

        bedrock = mock.MagicMock()
        bedrock.converse.side_effect = capture_converse
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert len(prompts_seen) == 2
        assert prompts_seen[0] != prompts_seen[1]

    def test_no_regen_at_zero_bad_claims(self):
        verdicts = [SUPPORTED_VERDICT]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 0
        written = s3.put_object.call_args.kwargs['Body'].decode()
        assert written == ORIGINAL_SUMMARY

    def test_validated_summary_written_to_s3(self):
        verdicts = [SUPPORTED_VERDICT]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        put_key = s3.put_object.call_args.kwargs['Key']
        assert put_key == 'summaries/job-assemble-001/validated_summary.txt'

    def test_validated_summary_key_in_return(self):
        verdicts = [SUPPORTED_VERDICT]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(verdicts)

        with mock.patch.object(summary_assembler_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(summary_assembler_handler, 's3_client', s3):
            result = summary_assembler_handler.lambda_handler(BASE_EVENT, None)

        assert 'validated_summary_key' in result
        assert result['validated_summary_key'].endswith('validated_summary.txt')
