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
      type   = "US_SSN"
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
}

resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "Initial version"
}

resource "aws_bedrock_prompt" "classifier" {
  name = "${local.name_prefix}-classifier"

  variants {
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

resource "aws_bedrock_prompt" "lab_result" {
  name = "${local.name_prefix}-lab-result"

  variants {
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
        text = file("${path.module}/../prompts/lab_result_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrock_prompt" "doctors_notes" {
  name = "${local.name_prefix}-doctors-notes"

  variants {
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
        text = file("${path.module}/../prompts/doctors_notes_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrock_prompt" "injury_doc" {
  name = "${local.name_prefix}-injury-doc"

  variants {
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
        text = file("${path.module}/../prompts/injury_doc_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrock_prompt" "visit_assessment" {
  name = "${local.name_prefix}-visit-assessment"

  variants {
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
        text = file("${path.module}/../prompts/visit_assessment_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrock_prompt" "psych_eval" {
  name = "${local.name_prefix}-psych-eval"

  variants {
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
        text = file("${path.module}/../prompts/psych_eval_prompt.txt")
      }
    }
  }

  default_variant = "default"
  tags            = local.common_tags
}

resource "aws_bedrock_prompt_version" "classifier" {
  prompt_arn  = aws_bedrock_prompt.classifier.arn
  description = "Initial classifier prompt version"
}

resource "aws_bedrock_prompt_version" "lab_result" {
  prompt_arn  = aws_bedrock_prompt.lab_result.arn
  description = "Initial lab result extraction prompt version"
}

resource "aws_bedrock_prompt_version" "doctors_notes" {
  prompt_arn  = aws_bedrock_prompt.doctors_notes.arn
  description = "Initial doctor's notes extraction prompt version"
}

resource "aws_bedrock_prompt_version" "injury_doc" {
  prompt_arn  = aws_bedrock_prompt.injury_doc.arn
  description = "Initial injury documentation extraction prompt version"
}

resource "aws_bedrock_prompt_version" "visit_assessment" {
  prompt_arn  = aws_bedrock_prompt.visit_assessment.arn
  description = "Initial visit assessment extraction prompt version"
}

resource "aws_bedrock_prompt_version" "psych_eval" {
  prompt_arn  = aws_bedrock_prompt.psych_eval.arn
  description = "Initial psych eval extraction prompt version"
}
