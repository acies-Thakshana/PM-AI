# ----------------------------------------------------------------------------------------------
# uat: the values for the UAT environment
#
# STARTING POINT ONLY. This file is a copy of the dev values with the environment name and the UAT
# naming-sheet names changed, so the folder structure can be tried out. Lines marked REVIEW must be checked before real use.
# ----------------------------------------------------------------------------------------------

# ------------------------------------------------------------
# Acies practice mode
# This creates a fresh VPC and fresh app resources for learning.
# Do NOT use this file directly for CG unless CG approves VPC creation.
# ------------------------------------------------------------

project     = "uda327"
environment = "uat"
aws_region  = "us-east-1"

# For local practice only. Replace with your AWS CLI/SSO profile name.
# For CI/CD or CG platform-run execution, leave aws_profile empty and use role-based auth.
aws_profile     = ""  # REVIEW: this environment's AWS login (or leave empty and use an assumed role)
assume_role_arn = ""

owner       = "Nelson.Diaz@carrier.com"
cost_center = "103720"

# Carrier-required tags. The keys are lower-case exactly as in the AWS tag list (tag keys are case-sensitive).
additional_tags = {
  application        = "Program Manager AI"
  cost_center        = "103720"
  ix_app_id          = "app-04285"
  owner              = "Nelson.Diaz@carrier.com"
  DataClassification = "Internal"
}

# Create a new practice VPC similar to the manual E2E setup.
create_vpc           = false
vpc_cidr             = ""
public_subnet_cidrs  = ["", ""]  #These are sample values need to fil actual ones
private_subnet_cidrs = ["", ""]
enable_vpc_endpoints = true

# Create app-specific security groups.
create_security_groups = true
allowed_egress_cidrs   = [""]

# Backend sizing based on the manual ECS/Fargate setup.
container_port = 8000
ecs_cpu        = 1024
ecs_memory     = 4096

desired_count = 1

extra_cors_origins = []  # REVIEW: localhost is for development only

# ECR / app resources are created by OpenTofu.
# UAT name from the naming sheet (dev and prod use the default <project>-backend-<environment>)
ecr_repository_name       = "uda327-backend-ecr-uat"
create_ecr                = true
ecr_image_retention_count = 10
ecr_image_tag_mutability  = "MUTABLE"  # REVIEW: IMMUTABLE is recommended for UAT / PROD

# Practice only: let `tofu destroy` delete the ECR repo and S3 bucket even when they hold data.
# Apply once with these set to true BEFORE running `tofu destroy`.
ecr_force_delete = false  # REVIEW: keep false for UAT / PROD
s3_force_destroy = false  # REVIEW: keep false for UAT / PROD

create_s3_bucket           = true
create_dynamodb_tables     = true
create_iam_roles           = true
create_placeholder_secrets = true

# Current backend can keep OpenRouter wiring for practice.
# If you fully move to Bedrock, set enable_openrouter=false and update backend code accordingly.
enable_openrouter = false
enable_deepl      = false

# Bedrock + Translate added for the new version.
enable_bedrock           = true
enable_translate         = true
bedrock_cheap_model_id   = "us.amazon.nova-pro-v1:0"
bedrock_default_model_id = "us.anthropic.claude-haiku-4-5-20251001"
bedrock_strong_model_id  = "us.anthropic.claude-sonnet-4-6"
bedrock_model_arns       = ["*"]  # REVIEW: list the approved model ARN(s)

# API sign-in. With AWS storage on, the backend needs Entra OR allow_anon.
# Practice only: no sign-in. For a client environment set the two Entra IDs instead.
allow_anon      = true  # REVIEW: false for UAT / PROD; set the Entra ids below instead
entra_tenant_id = ""
entra_client_id = ""

# Amplify is part of target architecture, but enable only after repo URL/access is ready.
enable_amplify         = true
amplify_repository_url = "https://github.com/Carrier-Intelligence/UDA-327-CST-Virtual-C-I-Program-Manager-Report-Agent-AWS.git"
amplify_branch_name    = "uda327-uat1-infra"  # REVIEW: this environment's Git branch

# REVIEW: prompt ids belong to an AWS account + region. Create the prompts in this environment's
# account (python scripts/bedrock_prompts.py create) and paste ITS ids here.
# Bedrock Prompt Management ids (from: python scripts/bedrock_prompts.py create).
# Without these the backend answers 503 "No system prompt for 'planner_agent'".
bedrock_prompt_ids = {

}
