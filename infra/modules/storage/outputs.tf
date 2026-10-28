output "s3_bucket_name" {
  description = "Name of the data bucket (created here or the client's)."
  value       = local.s3_bucket_name
}

output "s3_bucket_arn" {
  description = "ARN of the data bucket (for IAM permissions)."
  value       = local.s3_bucket_arn
}
