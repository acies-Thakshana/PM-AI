output "openrouter_secret_arn" {
  description = "OpenRouter secret ARN, or empty."
  value       = local.openrouter_secret_arn
}

output "deepl_secret_arn" {
  description = "DeepL secret ARN, or empty."
  value       = local.deepl_secret_arn
}

output "secret_arns" {
  description = "All existing secret ARNs (for IAM permissions)."
  value       = local.secret_arns
}

output "container_secrets" {
  description = "Name + ARN pairs the ECS container receives as secrets."
  value       = local.ecs_container_secrets
}
