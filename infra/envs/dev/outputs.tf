output "name_prefix" {
  description = "Common resource name prefix."
  value       = local.name_prefix
}

output "vpc_id" {
  description = "Created or referenced VPC ID."
  value       = module.network.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs used by VPC Link, ALB, and ECS."
  value       = module.network.private_subnet_ids
}

output "ecr_repository_url" {
  description = "Backend ECR repository URL."
  value       = module.registry.repository_url
}

output "docker_build_and_push_hint" {
  description = "Command hint for building and pushing the backend image. Replace profile if required."
  value = join("\n", [
    "cd backend",
    "docker build -t ${module.registry.repository_name}:${var.image_tag} .",
    "aws ecr get-login-password --region ${var.aws_region}${var.aws_profile != "" ? " --profile ${var.aws_profile}" : ""} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com",
    "docker tag ${module.registry.repository_name}:${var.image_tag} ${module.registry.repository_url}:${var.image_tag}",
    "docker push ${module.registry.repository_url}:${var.image_tag}"
  ])
}

output "api_gateway_url" {
  description = "Public API Gateway URL for frontend backend calls."
  value       = module.api.invoke_url
}

output "internal_alb_dns_name" {
  description = "Internal ALB DNS name. This is private, not an internet URL."
  value       = module.compute.alb_dns_name
}

output "s3_bucket_name" {
  description = "App data bucket name."
  value       = module.storage.s3_bucket_name
}

output "dynamodb_table_names" {
  description = "DynamoDB table names used by the backend."
  value       = module.database.dynamodb_table_names
}

output "openrouter_secret_arn" {
  description = "OpenRouter secret ARN, if enabled. Insert the value separately."
  value       = module.secrets.openrouter_secret_arn
}

output "deepl_secret_arn" {
  description = "DeepL secret ARN, if enabled. Insert the value separately."
  value       = module.secrets.deepl_secret_arn
}

output "bedrock_cheap_model_id" {
  description = "Configured cheap Bedrock model."
  value       = var.enable_bedrock ? var.bedrock_cheap_model_id : ""
}

output "bedrock_default_model_id" {
  description = "Configured default Bedrock model."
  value       = var.enable_bedrock ? var.bedrock_default_model_id : ""
}

output "bedrock_strong_model_id" {
  description = "Configured strong Bedrock model."
  value       = var.enable_bedrock ? var.bedrock_strong_model_id : ""
}

output "amplify_app_id" {
  description = "Amplify app ID, used for `aws amplify start-job --app-id ...`."
  value       = var.enable_amplify ? module.frontend.app_id : ""
}

output "frontend_origin" {
  description = "Frontend URL (the origin that CORS allows). Empty if Amplify is disabled."
  value       = module.frontend.amplify_origin
}

output "cors_origins" {
  description = "Every origin allowed by API Gateway CORS, S3 CORS and the backend."
  value       = local.cors_origins
}

output "amplify_default_domain" {
  description = "Amplify default domain, if Amplify is enabled."
  value       = var.enable_amplify ? module.frontend.default_domain : ""
}

output "swp_secret_arn" {
  description = "SensiWatch (SWP) secret ARN, if enabled. Insert the value separately (see the deploy steps)."
  value       = module.secrets.swp_secret_arn
}
