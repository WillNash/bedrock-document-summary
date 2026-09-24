{
  "Comment": "Claim-level faithfulness validator for medical document summaries",
  "StartAt": "ExtractClaims",
  "States": {
    "ExtractClaims": {
      "Type": "Task",
      "Resource": "${claim_extractor_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkClaimValidationFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "TriageClaims"
    },
    "TriageClaims": {
      "Type": "Task",
      "Resource": "${claim_triager_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkClaimValidationFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "AssessClaims"
    },
    "AssessClaims": {
      "Type": "Task",
      "Resource": "${claim_assessor_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkClaimValidationFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "AssembleSummary"
    },
    "AssembleSummary": {
      "Type": "Task",
      "Resource": "${summary_assembler_lambda_arn}",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "MarkClaimValidationFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ClaimValidationComplete"
    },
    "MarkClaimValidationFailed": {
      "Type": "Pass",
      "Next": "ClaimValidationFailed"
    },
    "ClaimValidationFailed": {
      "Type": "Fail",
      "Error": "ClaimValidationFailed",
      "Cause": "Claim validation sub-pipeline failed — see claim-validator Lambda logs for details"
    },
    "ClaimValidationComplete": {
      "Type": "Succeed"
    }
  }
}
