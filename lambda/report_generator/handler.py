"""
Step Functions task — GenerateReport.

Calls Claude Sonnet via Bedrock to synthesise variance and gold-accuracy
statistics into a human-readable Markdown narrative. The summary texts
themselves are never passed here — only numeric scores.

Input:  accumulated Step Functions state (experiment_id, config, variance_results,
        gold_results if present)
Output (merged into $.report via ResultPath): {"narrative_md": "..."}
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_client = boto3.client('bedrock-runtime')

REPORT_MODEL_ID = 'us.anthropic.claude-sonnet-4-6'


def _fmt_stats(stats):
    return (
        f"mean={stats['mean']:.4f}, std={stats['std']:.4f}, "
        f"min={stats['min']:.4f}, max={stats['max']:.4f}"
    )


def _build_prompt(event):
    experiment_id = event['experiment_id']
    config = event.get('config', {})
    successful_n = event.get('successful_n', 0)
    doc_type = event.get('doc_type', 'unknown')
    variance = event.get('variance_results', {})
    gold = event.get('gold_results')

    lines = [
        f'Experiment ID: {experiment_id}',
        f'Document type: {doc_type}',
        f'Successful runs: {successful_n}',
    ]
    if config.get('description'):
        lines.append(f'Description: {config["description"]}')

    lines += ['', '## Variance (inter-run consistency)']
    if 'embedding_cosine' in variance:
        lines.append(f'Embedding cosine similarity — {_fmt_stats(variance["embedding_cosine"])}')
    if 'tfidf_cosine' in variance:
        lines.append(f'TF-IDF cosine similarity    — {_fmt_stats(variance["tfidf_cosine"])}')

    if gold:
        lines += ['', '## Gold-standard accuracy']
        if 'embedding_cosine' in gold:
            stats = gold['embedding_cosine']
            lines.append(f'Embedding cosine vs gold — {_fmt_stats(stats)}')
            per_run = ', '.join(
                f'run {r}: {s:.4f}'
                for r, s in zip(stats.get('run_numbers', []), stats['scores'])
            )
            lines.append(f'  Per-run: {per_run}')
        if 'bertscore_f1' in gold:
            stats = gold['bertscore_f1']
            lines.append(f'BERTScore F1 vs gold    — {_fmt_stats(stats)}')
            per_run = ', '.join(
                f'run {r}: {s:.4f}'
                for r, s in zip(stats.get('run_numbers', []), stats['scores'])
            )
            lines.append(f'  Per-run: {per_run}')

    stats_block = '\n'.join(lines)

    return (
        'You are a technical evaluator for an AI summarisation pipeline. '
        'Write a concise Markdown report (200–400 words) analysing the experiment results below.\n\n'
        'Cover: (1) inter-run consistency based on the variance metrics, '
        '(2) accuracy against the gold standard if provided, '
        '(3) any outlier runs worth investigating, '
        '(4) an overall reliability verdict for this document type.\n\n'
        'Use plain Markdown. Start with a ## Summary heading. Do not repeat raw numbers excessively — '
        'interpret them. BERTScore F1 typical range for similar medical texts is 0.84–0.97.\n\n'
        f'--- EXPERIMENT RESULTS ---\n{stats_block}\n--- END RESULTS ---'
    )


def lambda_handler(event, context):
    prompt = _build_prompt(event)
    model_id = os.environ.get('REPORT_MODEL_ID', REPORT_MODEL_ID)

    response = bedrock_client.converse(
        modelId=model_id,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': 1024, 'temperature': 0.3},
    )

    narrative_md = response['output']['message']['content'][0]['text'].strip()

    logger.info(json.dumps({
        'experiment_id': event.get('experiment_id'),
        'action': 'narrative_generated',
        'output_tokens': response.get('usage', {}).get('outputTokens', 0),
    }))

    return {'narrative_md': narrative_md}
