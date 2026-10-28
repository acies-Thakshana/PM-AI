variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "api_url" {
  description = "Public API URL given to the frontend build as VITE_API_BASE_URL (from the api module)."
  type        = string
}

variable "enable_amplify" {
  description = "Create Amplify app/branch for frontend. Requires repository details."
  type        = bool
}

variable "amplify_repository_url" {
  description = "Git repository URL for Amplify."
  type        = string
}

variable "amplify_branch_name" {
  description = "Branch deployed by Amplify."
  type        = string
}

variable "amplify_access_token" {
  description = "Optional Git access token for Amplify. Prefer CG-managed repo connection; token may enter state."
  type        = string
  sensitive   = true
}
