resource "aws_sfn_state_machine" "pipeline" {
  name = "${local.name_prefix}-pipeline"
  type = "EXPRESS"

  role_arn = aws_iam_role.sfn.arn

  definition = templatefile("${path.module}/state_machine.json.tpl", {
    classifier_lambda_arn   = aws_lambda_function.classifier.arn
    extractor_lambda_arn    = aws_lambda_function.extractor.arn
    validator_lambda_arn    = aws_lambda_function.validator.arn
    renderer_lambda_arn     = aws_lambda_function.renderer.arn
    fail_handler_lambda_arn = aws_lambda_function.fail_handler.arn
    claim_validator_sm_arn  = aws_sfn_state_machine.claim_validator.arn
  })

  depends_on = [
    aws_iam_role_policy.sfn_events_managed_rule,
    aws_iam_role_policy.sfn_pipeline_claim_validator,
  ]

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions["pipeline"].arn}:*"
    include_execution_data = false # intentionally false — execution input contains PHI document content
    level                  = "ERROR"
  }

  tags = local.common_tags
}

resource "aws_sfn_state_machine" "claim_validator" {
  name = "${local.name_prefix}-claim-validator"
  type = "EXPRESS"

  role_arn = aws_iam_role.sfn_claim_validator.arn

  definition = templatefile("${path.module}/claim_validator_sm.json.tpl", {
    claim_extractor_lambda_arn   = aws_lambda_function.claim_extractor.arn
    claim_triager_lambda_arn     = aws_lambda_function.claim_triager.arn
    claim_assessor_lambda_arn    = aws_lambda_function.claim_assessor.arn
    summary_assembler_lambda_arn = aws_lambda_function.summary_assembler.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions["claim-validator"].arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  tags = local.common_tags
}

resource "aws_sfn_state_machine" "comparison" {
  name = "${local.name_prefix}-comparison"
  type = "STANDARD"

  role_arn = aws_iam_role.sfn_comparison.arn

  definition = templatefile("${path.module}/comparison_sm.json.tpl", {
    summary_collector_lambda_arn       = aws_lambda_function.summary_collector.arn
    variance_scorer_lambda_arn         = aws_lambda_function.variance_scorer.arn
    gold_scorer_lambda_arn             = aws_lambda_function.gold_scorer.arn
    report_generator_lambda_arn        = aws_lambda_function.report_generator.arn
    report_writer_lambda_arn           = aws_lambda_function.report_writer.arn
    comparison_fail_handler_lambda_arn = aws_lambda_function.comparison_fail_handler.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions["comparison"].arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  tags = local.common_tags
}
