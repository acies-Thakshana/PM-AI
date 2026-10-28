output "dynamodb_table_names" {
  description = "Map of table names: profiles, docs, audit_log, chats."
  value       = local.dynamodb_table_names
}

output "dynamodb_table_arns" {
  description = "List of the table ARNs (for IAM permissions)."
  value       = local.dynamodb_table_arns
}
