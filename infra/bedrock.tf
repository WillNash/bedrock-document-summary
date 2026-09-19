resource "aws_bedrock_guardrail" "main" {
  name                      = "${local.name_prefix}-phi-guardrail"
  blocked_input_messaging   = "This request contains content that cannot be processed."
  blocked_outputs_messaging = "The response contains content that cannot be displayed."

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "NAME"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "US_PASSPORT_NUMBER"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "DRIVER_ID"
      action = "ANONYMIZE"
    }
  }

  tags = local.common_tags

  lifecycle {
    # Provider bug: description is returned as unknown post-create, causing perpetual drift.
    ignore_changes = [description]
  }
}

resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "Initial version"
}

resource "aws_bedrockagent_prompt" "classifier" {
  name = "${local.name_prefix}-classifier"

  variant {
    name          = "default"
    model_id      = var.bedrock_classifier_model_id
    template_type = "TEXT"

    inference_configuration {
      text {
        temperature = 0
        max_tokens  = 20
      }
    }

    template_configuration {
      text {
        text = file("${path.module}/../prompts/classifier_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrockagent_prompt" "extraction" {
  for_each = local.extraction_doc_types
  name     = "${local.name_prefix}-${replace(each.key, "_", "-")}"

  variant {
    name          = "default"
    model_id      = var.bedrock_model_id
    template_type = "TEXT"

    inference_configuration {
      text {
        temperature = 0
        max_tokens  = 4096
      }
    }

    template_configuration {
      text {
        text = file("${path.module}/../prompts/${each.key}_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}
