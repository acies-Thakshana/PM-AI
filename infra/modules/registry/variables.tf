variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "create_ecr" {
  description = "true = create ECR repository; false = use existing_ecr_repository_url."
  type        = bool
}

variable "existing_ecr_repository_url" {
  description = "Existing ECR repository URL when create_ecr=false."
  type        = string
}

variable "ecr_repository_name" {
  description = "ECR repository name when create_ecr=true. Empty uses <project>-backend-<environment>."
  type        = string
}

variable "ecr_image_retention_count" {
  description = "Number of recent ECR images to retain."
  type        = number
}

variable "ecr_force_delete" {
  description = "true = `tofu destroy` also deletes the repo with its images inside. Practice/dev only; keep false for prod. Must be applied once BEFORE the destroy."
  type        = bool
}

variable "ecr_image_tag_mutability" {
  description = "ECR image tag mutability. MUTABLE is easier for practice; IMMUTABLE is better for prod."
  type        = string

  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.ecr_image_tag_mutability)
    error_message = "ecr_image_tag_mutability must be MUTABLE or IMMUTABLE."
  }
}
