# Guardrail is created and versioned by scripts/ensure_guardrail.sh (called from the
# deploy workflow) because the hashicorp/aws provider returns unknown values for computed
# attributes post-create, causing perpetual destroy/recreate cycles. The guardrail ID
# and version are passed in as variables.

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

resource "aws_bedrockagent_prompt_version" "classifier" {
  prompt_arn  = aws_bedrockagent_prompt.classifier.arn
  description = "Pinned version managed by Terraform — do not use DRAFT in Lambda env vars"
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

resource "aws_bedrockagent_prompt_version" "extraction" {
  for_each    = local.extraction_doc_types
  prompt_arn  = aws_bedrockagent_prompt.extraction[each.key].arn
  description = "Pinned version managed by Terraform — do not use DRAFT in Lambda env vars"
}
