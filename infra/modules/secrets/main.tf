# ----------------------------------------------------------------------------------------------
# Module: secrets
#
# Empty Secrets Manager containers for the OpenRouter / DeepL API keys and the SensiWatch (SWP) API
# credentials, and the lists the other modules need (secret ARNs for IAM, name+ARN pairs for the container).
#
# OpenRouter and DeepL are switched off in the current setup (enable_openrouter / enable_deepl = false).
# The SWP secret is one JSON secret holding every SWP credential; each key becomes its own container
# environment variable. Secret VALUES are never stored here: put them in with the AWS CLI.
# Moved unchanged from secrets.tf (+ the secret locals from locals.tf).
# ----------------------------------------------------------------------------------------------

locals {
  # Secrets. Secret values are intentionally NOT managed by OpenTofu.
  openrouter_secret_arn = var.enable_openrouter ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.openrouter[0].arn : var.openrouter_secret_arn) : ""
  deepl_secret_arn      = var.enable_deepl ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.deepl[0].arn : var.deepl_secret_arn) : ""
  swp_secret_arn        = var.enable_swp ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.swp[0].arn : var.swp_secret_arn) : ""
  secret_arns           = compact([local.openrouter_secret_arn, local.deepl_secret_arn, local.swp_secret_arn])

  # The keys of the SWP secret's JSON. All five must exist in it (a key may be an empty string, e.g. no second
  # trip key), or the container cannot start. The names are the environment variables the backend reads.
  swp_secret_keys = ["SWP_SECURITY_KEY", "SWP_TRIP_KEY", "SWP_TRIP_KEY_2", "SWP_USER", "SWP_PASS"]

  ecs_container_secrets = concat(
    var.enable_openrouter ? [{
      name      = "OPENROUTER_API_KEY"
      valueFrom = local.openrouter_secret_arn
    }] : [],
    var.enable_deepl ? [{
      name      = "DEEPL_API_KEY"
      valueFrom = local.deepl_secret_arn
    }] : [],
    var.enable_swp ? [for key in local.swp_secret_keys : {
      name      = key
      valueFrom = "${local.swp_secret_arn}:${key}::" # <secret arn>:<json key>:: reads one key of the JSON secret
    }] : []
  )
}

resource "aws_secretsmanager_secret" "openrouter" {
  count = var.create_placeholder_secrets && var.enable_openrouter ? 1 : 0

  name                    = "${var.project}-openrouter-api-key-${var.environment}"
  description             = "OpenRouter API key placeholder for ${var.project}-${var.environment}. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project}-openrouter-secret-${var.environment}"
  }
}

resource "aws_secretsmanager_secret" "deepl" {
  count = var.create_placeholder_secrets && var.enable_deepl ? 1 : 0

  name                    = "${var.project}-deepl-api-key-${var.environment}"
  description             = "DeepL API key placeholder for ${var.project}-${var.environment}. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project}-deepl-secret-${var.environment}"
  }
}

resource "aws_secretsmanager_secret" "swp" {
  count = var.create_placeholder_secrets && var.enable_swp ? 1 : 0

  name                    = "${var.project}-swp-api-${var.environment}"
  description             = "SensiWatch (SWP) API credentials (JSON with ${join(", ", local.swp_secret_keys)}) for ${var.project}-${var.environment}. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project}-swp-secret-${var.environment}"
  }
}
