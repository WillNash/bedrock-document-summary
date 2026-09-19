{
  "Comment": "Medical document summarization pipeline — classify, extract, validate, render",
  "StartAt": "ClassifyDocument",
  "States": {
    "ClassifyDocument": {
      "Type": "Task",
      "Resource": "${classifier_lambda_arn}",
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
          "Next": "MarkJobFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ExtractData"
    },
    "ExtractData": {
      "Type": "Task",
      "Resource": "${extractor_lambda_arn}",
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
          "Next": "MarkJobFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ValidateData"
    },
    "ValidateData": {
      "Type": "Task",
      "Resource": "${validator_lambda_arn}",
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
          "Next": "MarkJobFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "RenderSummary"
    },
    "RenderSummary": {
      "Type": "Task",
      "Resource": "${renderer_lambda_arn}",
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
          "Next": "MarkJobFailed",
          "ResultPath": "$.error"
        }
      ],
      "Next": "JobComplete"
    },
    "MarkJobFailed": {
      "Type": "Task",
      "Resource": "${fail_handler_lambda_arn}",
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
      "Next": "JobFailed"
    },
    "JobFailed": {
      "Type": "Fail",
      "Error": "PipelineFailed",
      "Cause": "Document processing failed — see fail_handler Lambda logs for details"
    },
    "JobComplete": {
      "Type": "Succeed"
    }
  }
}
