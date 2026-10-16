variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "aws_region" {
  description = "AWS region where resources are deployed."
  type        = string
}

variable "create_vpc" {
  description = "true = create a new VPC for Acies practice; false = use existing VPC/subnets, expected for CG."
  type        = bool
}

variable "vpc_cidr" {
  description = "CIDR for newly-created practice VPC. Ignored when create_vpc=false."
  type        = string
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs for practice VPC. Ignored when create_vpc=false."
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs for practice VPC. Ignored when create_vpc=false."
  type        = list(string)
}

variable "existing_vpc_id" {
  description = "Existing CG VPC ID when create_vpc=false."
  type        = string
}

variable "existing_private_subnet_ids" {
  description = "Existing private subnet IDs for API Gateway VPC Link, internal ALB, and ECS when create_vpc=false."
  type        = list(string)
}

variable "existing_private_route_table_ids" {
  description = "Private route table IDs for S3/DynamoDB VPC endpoints when create_vpc=false and enable_vpc_endpoints=true."
  type        = list(string)
}

variable "enable_vpc_endpoints" {
  description = "Create S3 and DynamoDB gateway VPC endpoints for private access. Disable if CG already provides them."
  type        = bool
}
