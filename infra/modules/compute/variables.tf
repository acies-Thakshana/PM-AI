variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "vpc_id" {
  description = "VPC the load balancer and target group live in (from the network module)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets for the load balancer and the ECS tasks (from the network module)."
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "Firewall of the load balancer (from the security module)."
  type        = string
}

variable "ecs_security_group_id" {
  description = "Firewall of the ECS tasks (from the security module)."
  type        = string
}

variable "ecs_execution_role_arn" {
  description = "Execution role ARN (from the iam module)."
  type        = string
}

variable "ecs_task_role_arn" {
  description = "Task role ARN (from the iam module)."
  type        = string
}

variable "ecr_repository_url" {
  description = "Image repository address (from the registry module)."
  type        = string
}

variable "container_secrets" {
  description = "Name + ARN pairs injected into the container as secrets (from the secrets module)."
  type        = list(object({ name = string, valueFrom = string }))
}

variable "cors_origins" {
  description = "Allowed browser origins, passed to the container as CORS_ORIGINS."
  type        = list(string)
}

variable "s3_bucket_name" {
  description = "Data bucket name, passed to the container as S3_BUCKET (from the storage module)."
  type        = string
}

variable "dynamodb_table_names" {
  description = "Table names (profiles, docs, audit_log, chats), passed to the container as DDB_* (from the database module)."
  type        = map(string)
}

variable "aws_region" {
  description = "AWS region where resources are deployed."
  type        = string
}

variable "container_port" {
  description = "FastAPI backend container port."
  type        = number
}

variable "image_tag" {
  description = "Backend Docker image tag used by ECS."
  type        = string
}

variable "ecs_cpu" {
  description = "Fargate task CPU units. 1024 = 1 vCPU."
  type        = number
}

variable "ecs_memory" {
  description = "Fargate task memory in MiB."
  type        = number
}

variable "desired_count" {
  description = "Number of ECS backend tasks. Keep 0 for first apply; set 1 after image/secrets are ready."
  type        = number
}

variable "cpu_architecture" {
  description = "Container CPU architecture. Use X86_64 if Docker image was built on a normal Windows/Intel machine."
  type        = string

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "enable_container_insights" {
  description = "Enable ECS container insights."
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "alb_idle_timeout_seconds" {
  description = "Internal ALB idle timeout."
  type        = number
}

variable "alb_listener_protocol" {
  description = "Internal ALB listener protocol. HTTP is aligned to the current setup; use HTTPS only if CG requires it."
  type        = string

  validation {
    condition     = contains(["HTTP", "HTTPS"], var.alb_listener_protocol)
    error_message = "alb_listener_protocol must be HTTP or HTTPS."
  }
}

variable "alb_listener_port" {
  description = "Internal ALB listener port."
  type        = number
}

variable "alb_certificate_arn" {
  description = "ACM certificate ARN if alb_listener_protocol=HTTPS."
  type        = string
}

variable "health_check_path" {
  description = "ALB health check path. The backend must return 200 here."
  type        = string
}

variable "health_check_matcher" {
  description = "Expected success code for target group health check."
  type        = string
}

variable "health_check_interval_seconds" {
  description = "Target group health check interval."
  type        = number
}

variable "health_check_timeout_seconds" {
  description = "Target group health check timeout."
  type        = number
}

variable "health_check_healthy_threshold" {
  description = "Successful health checks before target is healthy."
  type        = number
}

variable "health_check_unhealthy_threshold" {
  description = "Failed health checks before target is unhealthy."
  type        = number
}

variable "enable_bedrock" {
  description = "Enable Bedrock environment variables and IAM permissions."
  type        = bool
}

variable "bedrock_cheap_model_id" {
  description = "Bedrock model for the cheap, high-volume calls. Reaches the container as BEDROCK_CHEAP_MODEL."
  type        = string
}

variable "bedrock_default_model_id" {
  description = "Bedrock model for the everyday calls. Reaches the container as BEDROCK_DEFAULT_MODEL."
  type        = string
}

variable "bedrock_strong_model_id" {
  description = "Bedrock model for the heavy reasoning calls (planner, code writing). Reaches the container as BEDROCK_STRONG_MODEL."
  type        = string
}

variable "bedrock_prompt_ids" {
  description = "Map of call name to Bedrock Prompt Management id:version."
  type        = map(string)
}

variable "allow_anon" {
  description = "true = run the API without sign-in (ALLOW_ANON=1). Practice only; leave false for client environments."
  type        = bool
}

variable "entra_tenant_id" {
  description = "Microsoft Entra tenant ID. Set together with entra_client_id to require sign-in. Empty = not set."
  type        = string
}

variable "entra_client_id" {
  description = "Microsoft Entra API app (client) ID. Set together with entra_tenant_id. Empty = not set."
  type        = string
}
