# ----------------------------------------------------------------------------------------------
# Environment entry point (IDENTICAL in dev, uat and prod)
#
# This file only wires the modules together. All the real code is in ../../modules.
# What differs between environments lives ONLY in terraform.tfvars (the values) and backend.tf (the state).
# ----------------------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  # Only used by the name_prefix output. Resource names are built inside the modules as
  # <project>-<thing>-<environment> (for example uda327-alb-dev).
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge({
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "opentofu"
    Owner       = var.owner
    CostCenter  = var.cost_center
  }, var.additional_tags)

  # Every origin allowed to call the API (API Gateway CORS, S3 CORS and the backend's CORS_ORIGINS).
  # The list is built with a conditional on a known flag, not compact(), so its LENGTH is known at
  # plan time (the S3 CORS rule below needs that).
  cors_origins = concat(var.extra_cors_origins, var.enable_amplify ? [module.frontend.amplify_origin] : [])
}

# Network: VPC, subnets, gateways, routes, endpoints
module "network" {
  source = "../../modules/network"

  project                          = var.project
  environment                      = var.environment
  aws_region                       = var.aws_region
  create_vpc                       = var.create_vpc
  vpc_cidr                         = var.vpc_cidr
  public_subnet_cidrs              = var.public_subnet_cidrs
  private_subnet_cidrs             = var.private_subnet_cidrs
  existing_vpc_id                  = var.existing_vpc_id
  existing_private_subnet_ids      = var.existing_private_subnet_ids
  existing_private_route_table_ids = var.existing_private_route_table_ids
  enable_vpc_endpoints             = var.enable_vpc_endpoints
}

# Security: the three chained firewalls
module "security" {
  source = "../../modules/security"

  project                            = var.project
  environment                        = var.environment
  vpc_id                             = module.network.vpc_id
  create_security_groups             = var.create_security_groups
  existing_vpclink_security_group_id = var.existing_vpclink_security_group_id
  existing_alb_security_group_id     = var.existing_alb_security_group_id
  existing_ecs_security_group_id     = var.existing_ecs_security_group_id
  allowed_egress_cidrs               = var.allowed_egress_cidrs
  alb_listener_port                  = var.alb_listener_port
  container_port                     = var.container_port
}

# Registry: the ECR repository for the backend image
module "registry" {
  source = "../../modules/registry"

  environment                 = var.environment
  project                     = var.project
  create_ecr                  = var.create_ecr
  existing_ecr_repository_url = var.existing_ecr_repository_url
  ecr_repository_name         = var.ecr_repository_name
  ecr_image_retention_count   = var.ecr_image_retention_count
  ecr_force_delete            = var.ecr_force_delete
  ecr_image_tag_mutability    = var.ecr_image_tag_mutability
}

# Secrets: legacy API-key containers (off today)
module "secrets" {
  source = "../../modules/secrets"

  project                    = var.project
  environment                = var.environment
  create_placeholder_secrets = var.create_placeholder_secrets
  enable_openrouter          = var.enable_openrouter
  openrouter_secret_arn      = var.openrouter_secret_arn
  enable_deepl               = var.enable_deepl
  deepl_secret_arn           = var.deepl_secret_arn
  enable_swp                 = var.enable_swp
  swp_secret_keys            = var.swp_secret_keys
}

# Storage: the S3 data bucket
module "storage" {
  source = "../../modules/storage"

  project                           = var.project
  environment                       = var.environment
  cors_origins                      = local.cors_origins
  create_s3_bucket                  = var.create_s3_bucket
  existing_s3_bucket_name           = var.existing_s3_bucket_name
  s3_force_destroy                  = var.s3_force_destroy
  s3_bucket_name                    = var.s3_bucket_name
  s3_encryption_type                = var.s3_encryption_type
  kms_key_arn                       = var.kms_key_arn
  s3_cors_max_age_seconds           = var.s3_cors_max_age_seconds
  temporary_object_expiry_days      = var.temporary_object_expiry_days
  s3_noncurrent_version_expiry_days = var.s3_noncurrent_version_expiry_days
  s3_abort_multipart_days           = var.s3_abort_multipart_days
}

# Database: the four DynamoDB tables
module "database" {
  source = "../../modules/database"

  project                       = var.project
  environment                   = var.environment
  create_dynamodb_tables        = var.create_dynamodb_tables
  dynamodb_billing_mode         = var.dynamodb_billing_mode
  dynamodb_ttl_attribute        = var.dynamodb_ttl_attribute
  existing_dynamodb_table_names = var.existing_dynamodb_table_names
  existing_dynamodb_table_arns  = var.existing_dynamodb_table_arns
}

# IAM: execution role and task role
module "iam" {
  source = "../../modules/iam"

  project                         = var.project
  environment                     = var.environment
  s3_bucket_arn                   = module.storage.s3_bucket_arn
  dynamodb_table_arns             = module.database.dynamodb_table_arns
  secret_arns                     = module.secrets.secret_arns
  aws_region                      = var.aws_region
  create_iam_roles                = var.create_iam_roles
  existing_ecs_execution_role_arn = var.existing_ecs_execution_role_arn
  existing_ecs_task_role_arn      = var.existing_ecs_task_role_arn
  permissions_boundary_arn        = var.permissions_boundary_arn
  enable_translate                = var.enable_translate
  enable_bedrock                  = var.enable_bedrock
  bedrock_model_arns              = var.bedrock_model_arns
}

# Compute: load balancer + ECS (runs the backend container)
module "compute" {
  source = "../../modules/compute"

  project                          = var.project
  environment                      = var.environment
  vpc_id                           = module.network.vpc_id
  private_subnet_ids               = module.network.private_subnet_ids
  alb_security_group_id            = module.security.alb_security_group_id
  ecs_security_group_id            = module.security.ecs_security_group_id
  ecs_execution_role_arn           = module.iam.execution_role_arn
  ecs_task_role_arn                = module.iam.task_role_arn
  ecr_repository_url               = module.registry.repository_url
  container_secrets                = module.secrets.container_secrets
  cors_origins                     = local.cors_origins
  s3_bucket_name                   = module.storage.s3_bucket_name
  dynamodb_table_names             = module.database.dynamodb_table_names
  aws_region                       = var.aws_region
  container_port                   = var.container_port
  image_tag                        = var.image_tag
  ecs_cpu                          = var.ecs_cpu
  ecs_memory                       = var.ecs_memory
  desired_count                    = var.desired_count
  cpu_architecture                 = var.cpu_architecture
  enable_container_insights        = var.enable_container_insights
  log_retention_days               = var.log_retention_days
  alb_idle_timeout_seconds         = var.alb_idle_timeout_seconds
  alb_listener_protocol            = var.alb_listener_protocol
  alb_listener_port                = var.alb_listener_port
  alb_certificate_arn              = var.alb_certificate_arn
  health_check_path                = var.health_check_path
  health_check_matcher             = var.health_check_matcher
  health_check_interval_seconds    = var.health_check_interval_seconds
  health_check_timeout_seconds     = var.health_check_timeout_seconds
  health_check_healthy_threshold   = var.health_check_healthy_threshold
  health_check_unhealthy_threshold = var.health_check_unhealthy_threshold
  enable_bedrock                   = var.enable_bedrock
  bedrock_cheap_model_id           = var.bedrock_cheap_model_id
  bedrock_default_model_id         = var.bedrock_default_model_id
  bedrock_strong_model_id          = var.bedrock_strong_model_id
  bedrock_prompt_ids               = var.bedrock_prompt_ids
  allow_anon                       = var.allow_anon
  entra_tenant_id                  = var.entra_tenant_id
  entra_client_id                  = var.entra_client_id
}

# API: API Gateway + VPC Link in front of the load balancer
module "api" {
  source = "../../modules/api"

  project                          = var.project
  environment                      = var.environment
  cors_origins                     = local.cors_origins
  vpclink_security_group_id        = module.security.vpclink_security_group_id
  private_subnet_ids               = module.network.private_subnet_ids
  listener_arn                     = module.compute.listener_arn
  tls_server_name                  = var.alb_tls_server_name
  log_retention_days               = var.log_retention_days
  api_gateway_timeout_ms           = var.api_gateway_timeout_ms
  api_gateway_cors_max_age_seconds = var.api_gateway_cors_max_age_seconds
}

# Frontend: the Amplify app and branch
module "frontend" {
  source = "../../modules/frontend"

  project                = var.project
  api_url                = module.api.invoke_url
  environment            = var.environment
  enable_amplify         = var.enable_amplify
  amplify_repository_url = var.amplify_repository_url
  amplify_branch_name    = var.amplify_branch_name
  amplify_access_token   = var.amplify_access_token
}
