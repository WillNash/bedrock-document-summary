{
  "Comment": "Experiment comparison pipeline — collect summaries, compute variance, compare to gold, generate report",
  "StartAt": "CollectSummaries",
  "States": {
    "CollectSummaries": {
      "Type": "Task",
      "Resource": "${summary_collector_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkComparisonFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ComputeVariance"
    },
    "ComputeVariance": {
      "Type": "Task",
      "Resource": "${variance_scorer_lambda_arn}",
      "ResultPath": "$.variance_results",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 5,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkComparisonFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "CheckHasGold"
    },
    "CheckHasGold": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.has_gold",
          "BooleanEquals": true,
          "Next": "ComputeGoldAccuracy"
        }
      ],
      "Default": "GenerateReport"
    },
    "ComputeGoldAccuracy": {
      "Type": "Task",
      "Resource": "${gold_scorer_lambda_arn}",
      "ResultPath": "$.gold_results",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 5,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkComparisonFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "GenerateReport"
    },
    "GenerateReport": {
      "Type": "Task",
      "Resource": "${report_generator_lambda_arn}",
      "ResultPath": "$.report",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 5,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkComparisonFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "WriteReport"
    },
    "WriteReport": {
      "Type": "Task",
      "Resource": "${report_writer_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkComparisonFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ComparisonComplete"
    },
    "MarkComparisonFailed": {
      "Type": "Task",
      "Resource": "${comparison_fail_handler_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }
      ],
      "Next": "ComparisonFailed"
    },
    "ComparisonFailed": {
      "Type": "Fail",
      "Error": "ComparisonFailed",
      "Cause": "Experiment comparison pipeline failed — see comparison_fail_handler Lambda logs for details"
    },
    "ComparisonComplete": {
      "Type": "Succeed"
    }
  }
}
