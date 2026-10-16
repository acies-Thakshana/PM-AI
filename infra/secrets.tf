# ----------------------------------------------------------------------------------------------
# Secrets
#
# Empty Secrets Manager containers for the legacy OpenRouter / DeepL keys. Off today (enable_openrouter and
# enable_deepl are false), so this creates nothing. Secret VALUES are never stored here.
# ----------------------------------------------------------------------------------------------

locals {
  # Secrets. Secret values are intentionally NOT managed by OpenTofu.
  openrouter_secret_arn = var.enable_openrouter ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.openrouter[0].arn : var.openrouter_secret_arn) : ""
  deepl_secret_arn      = var.enable_deepl ? (var.create_placeholder_secrets ? aws_secretsmanager_secret.deepl[0].arn : var.deepl_secret_arn) : ""
  secret_arns           = compact([local.openrouter_secret_arn, local.deepl_secret_arn])

  ecs_container_secrets = concat(
    var.enable_openrouter ? [{
      name      = "OPENROUTER_API_KEY"
      valueFrom = local.openrouter_secret_arn
    }] : [],
    var.enable_deepl ? [{
      name      = "DEEPL_API_KEY"
      valueFrom = local.deepl_secret_arn
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
