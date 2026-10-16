output "dynamodb_table_names" {
  description = "Map of table names: sessions, profiles, docs, audit_log."
  value       = local.dynamodb_table_names
}

output "dynamodb_table_arns" {
  description = "List of the four table ARNs (for IAM permissions)."
  value       = local.dynamodb_table_arns
}
