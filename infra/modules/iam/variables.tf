variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the data bucket (from the storage module)."
  type        = string
}

variable "dynamodb_table_arns" {
  description = "ARNs of the DynamoDB tables (from the database module)."
  type        = list(string)
}

variable "secret_arns" {
  description = "ARNs of the secrets the roles may read (from the secrets module)."
  type        = list(string)
}

variable "aws_region" {
  description = "AWS region where resources are deployed."
  type        = string
}

variable "create_iam_roles" {
  description = "true = create ECS execution/task roles; false = use existing role ARNs."
  type        = bool
}

variable "existing_ecs_execution_role_arn" {
  description = "Existing ECS execution role ARN when create_iam_roles=false."
  type        = string
}

variable "existing_ecs_task_role_arn" {
  description = "Existing ECS application task role ARN when create_iam_roles=false."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Optional IAM permissions boundary ARN for roles created by this infra."
  type        = string
}

variable "enable_translate" {
  description = "Allow backend to call Amazon Translate."
  type        = bool
}

variable "enable_bedrock" {
  description = "Enable Bedrock environment variables and IAM permissions."
  type        = bool
}

variable "bedrock_model_arns" {
  description = "Allowed Bedrock model ARNs for IAM. Use specific ARNs when CG provides them; '*' is easiest for practice."
  type        = list(string)
}
