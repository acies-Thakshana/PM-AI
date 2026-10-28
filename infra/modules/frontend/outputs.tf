output "app_id" {
  description = "Amplify app id (empty if Amplify is disabled)."
  value       = var.enable_amplify ? aws_amplify_app.frontend[0].id : ""
}

output "default_domain" {
  description = "Amplify default domain (empty if disabled)."
  value       = var.enable_amplify ? aws_amplify_app.frontend[0].default_domain : ""
}

output "amplify_origin" {
  description = "Frontend URL that CORS must allow (empty if disabled)."
  value       = local.amplify_origin
}
