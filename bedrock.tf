resource "aws_bedrock_guardrail" "runtask_fulfillment" {
  name                      = "${local.solution_prefix}-guardrails"
  blocked_input_messaging   = "Unfortunately we are unable to provide response for this input"
  blocked_outputs_messaging = "Unfortunately we are unable to provide response for this input"
  description               = "Basic Bedrock Guardrail for sensitive info exfiltration"

  # detect and filter harmful user inputs and FM-generated outputs
  content_policy_config {
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "HATE"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "INSULTS"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "MISCONDUCT"
    }
    filters_config {
      input_strength  = "NONE"
      output_strength = "NONE"
      type            = "PROMPT_ATTACK"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "SEXUAL"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "VIOLENCE"
    }
  }

  # block / mask potential PII information
  sensitive_information_policy_config {
    pii_entities_config {
      action = "BLOCK"
      type   = "DRIVER_ID"
    }
    pii_entities_config {
      action = "BLOCK"
      type   = "PASSWORD"
    }
    pii_entities_config {
      action = "ANONYMIZE"
      type   = "EMAIL"
    }
    pii_entities_config {
      action = "ANONYMIZE"
      type   = "USERNAME"
    }
    pii_entities_config {
      action = "BLOCK"
      type   = "AWS_ACCESS_KEY"
    }
    pii_entities_config {
      action = "BLOCK"
      type   = "AWS_SECRET_KEY"
    }
  }

  # block select word / profanity
  word_policy_config {
    managed_word_lists_config {
      type = "PROFANITY"
    }
  }

  # custom topics for infrastructure-specific filtering
  topic_policy_config {
    topics_config {
      name       = "PublicS3Buckets"
      definition = "Discussions about making S3 buckets publicly accessible, disabling block public access settings, or allowing public read/write permissions on S3 buckets."
      examples = [
        "Make this S3 bucket public",
        "Disable block public access on the bucket",
        "Allow public read access to all objects"
      ]
      type = "DENY"
    }
    topics_config {
      name       = "UnencryptedStorage"
      definition = "Discussions about disabling encryption, removing encryption settings, or storing data without encryption on AWS storage services like S3, EBS, or RDS."
      examples = [
        "Remove encryption from this S3 bucket",
        "Disable encryption at rest",
        "Store data without encryption"
      ]
      type = "DENY"
    }
    topics_config {
      name       = "OverlyPermissiveIAM"
      definition = "Discussions about creating overly permissive IAM policies with wildcard actions or resources, granting admin access unnecessarily, or using * permissions without justification."
      examples = [
        "Grant full admin access to this role",
        "Use Action * and Resource * in the policy",
        "Give unrestricted permissions to all services"
      ]
      type = "DENY"
    }
  }

  tags = local.combined_tags
}

resource "aws_bedrock_guardrail_version" "runtask_fulfillment" {
  guardrail_arn = aws_bedrock_guardrail.runtask_fulfillment.guardrail_arn
  description   = "Initial version"
}
