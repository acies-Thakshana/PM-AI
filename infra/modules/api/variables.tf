variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "cors_origins" {
  description = "Browser origins API Gateway allows (extra origins plus the Amplify URL)."
  type        = list(string)
}

variable "vpclink_security_group_id" {
  description = "Firewall of the VPC Link (from the security module)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets the VPC Link uses (from the network module)."
  type        = list(string)
}

variable "listener_arn" {
  description = "Load balancer listener ARN the integration forwards to (from the compute module)."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "api_gateway_timeout_ms" {
  description = "API Gateway integration timeout in milliseconds. HTTP API maximum is 30000 ms."
  type        = number
}

variable "api_gateway_cors_max_age_seconds" {
  description = "API Gateway CORS preflight cache seconds."
  type        = number
}
