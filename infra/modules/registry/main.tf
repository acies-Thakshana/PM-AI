# ----------------------------------------------------------------------------------------------
# Module: registry
#
# The ECR repository that stores the backend Docker image, plus its clean-up (lifecycle) policy.
#
# With create_ecr = false the client's existing repository URL is used instead.
# Moved unchanged from ecr.tf (+ the ECR chooser locals from locals.tf).
# ----------------------------------------------------------------------------------------------

locals {
  # ECR selection.
  ecr_repository_name = var.ecr_repository_name != "" ? var.ecr_repository_name : "${var.project}-backend-${var.environment}"
  ecr_repository_url  = var.create_ecr ? aws_ecr_repository.backend[0].repository_url : var.existing_ecr_repository_url
}

resource "aws_ecr_repository" "backend" {
  count = var.create_ecr ? 1 : 0

  name                 = local.ecr_repository_name
  image_tag_mutability = var.ecr_image_tag_mutability
  force_delete         = var.ecr_force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project}-backend-ecr-${var.environment}"
  }
}

resource "aws_ecr_lifecycle_policy" "backend" {
  count = var.create_ecr ? 1 : 0

  repository = aws_ecr_repository.backend[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last ${var.ecr_image_retention_count} images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_image_retention_count
      }
      action = {
        type = "expire"
      }
    }]
  })
}
