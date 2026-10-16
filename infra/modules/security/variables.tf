variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "vpc_id" {
  description = "VPC the firewalls belong to (from the network module)."
  type        = string
}

variable "create_security_groups" {
  description = "true = create app security groups; false = use existing CG-provided security groups."
  type        = bool
}

variable "existing_vpclink_security_group_id" {
  description = "Existing security group for API Gateway VPC Link when create_security_groups=false."
  type        = string
}

variable "existing_alb_security_group_id" {
  description = "Existing security group for internal ALB when create_security_groups=false."
  type        = string
}

variable "existing_ecs_security_group_id" {
  description = "Existing security group for ECS tasks when create_security_groups=false."
  type        = string
}

variable "allowed_egress_cidrs" {
  description = "Outbound CIDRs for created security groups. CG may restrict this."
  type        = list(string)
}

variable "alb_listener_port" {
  description = "Internal ALB listener port."
  type        = number
}

variable "container_port" {
  description = "FastAPI backend container port."
  type        = number
}
