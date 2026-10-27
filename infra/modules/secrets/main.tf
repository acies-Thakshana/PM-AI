# ----------------------------------------------------------------------------------------------
# Module: secrets
#
# Empty Secrets Manager containers for the legacy OpenRouter / DeepL API keys, and the lists the
# other modules need (secret ARNs for IAM, name+ARN pairs for the container).
#
# Both are switched off in the current setup (enable_openrouter / enable_deepl = false), so this module
# creates nothing today. Secret VALUES are never stored here.
# Moved unchanged from secrets.tf (+ the secret locals from locals.tf).
# ----------------------------------------------------------------------------------------------

locals {
  # Secrets. Secret values are intentionally NOT managed by OpenTofu.
  openrouter_secret_arn = var.enable_openrouter ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.openrouter[0].arn : var.openrouter_secret_arn) : ""
  deepl_secret_arn      = var.enable_deepl ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.deepl[0].arn : var.deepl_secret_arn) : ""
  swp_secret_arn        = var.enable_swp ? aws_secretsmanager_secret.swp[0].arn : ""
  secret_arns           = compact([local.openrouter_secret_arn, local.deepl_secret_arn, local.swp_secret_arn])

  ecs_container_secrets = concat(
    var.enable_openrouter ? [{
      name      = "OPENROUTER_API_KEY"
      valueFrom = local.openrouter_secret_arn
    }] : [],
    var.enable_deepl ? [{
      name      = "DEEPL_API_KEY"
      valueFrom = local.deepl_secret_arn
    }] : [],
    # One secret holds all the SWP values as JSON. "<secret arn>:<key>::" hands ONE key of it to the container.
    [for key in(var.enable_swp ? var.swp_secret_keys : []) : {
      name      = key
      valueFrom = "${local.swp_secret_arn}:${key}::"
    }]
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
  count = var.enable_swp ? 1 : 0

  name                    = "${var.project}-swp-credentials-${var.environment}"
  description             = "SensiWatch (SWP) credentials for ${var.project}-${var.environment}, as JSON. Value must be inserted outside OpenTofu."
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project}-swp-secret-${var.environment}"
  }
}
