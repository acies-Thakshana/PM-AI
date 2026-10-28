# ----------------------------------------------------------------------------------------------
# Module: iam
#
# The two roles the containers use and what they may do:
#   - execution role: ECS pulls the image and writes logs (AWS managed policy), reads secrets if any
#   - task role: the app's own access to S3, DynamoDB, Bedrock (models + prompts) and Translate
#
# With create_iam_roles = false the client's role ARNs are used instead.
# Moved unchanged from iam.tf; the bucket / table / secret ARNs now arrive as inputs (var.*).
# ----------------------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  # IAM role selection.
  ecs_execution_role_arn = var.create_iam_roles ? aws_iam_role.ecs_execution[0].arn : var.existing_ecs_execution_role_arn
  ecs_task_role_arn      = var.create_iam_roles ? aws_iam_role.ecs_task[0].arn : var.existing_ecs_task_role_arn
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  count = var.create_iam_roles ? 1 : 0

  name                 = "${var.project}-ecs-execution-role-${var.environment}"
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = {
    Name = "${var.project}-ecs-execution-role-${var.environment}"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  count = var.create_iam_roles ? 1 : 0

  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_secrets" {
  count = var.create_iam_roles && length(var.secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  count = var.create_iam_roles && length(var.secret_arns) > 0 ? 1 : 0

  name   = "${var.project}-execution-secrets-${var.environment}"
  role   = aws_iam_role.ecs_execution[0].id
  policy = data.aws_iam_policy_document.ecs_execution_secrets[0].json
}

resource "aws_iam_role" "ecs_task" {
  count = var.create_iam_roles ? 1 : 0

  name                 = "${var.project}-ecs-task-role-${var.environment}"
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = {
    Name = "${var.project}-ecs-task-role-${var.environment}"
  }
}

data "aws_iam_policy_document" "app_permissions" {
  count = var.create_iam_roles ? 1 : 0

  statement {
    sid    = "S3AppDataAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = ["${var.s3_bucket_arn}/*"]
  }

  statement {
    sid       = "S3ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.s3_bucket_arn]
  }

  statement {
    sid    = "DynamoDBAppTablesAccess"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem"
    ]
    resources = concat(var.dynamodb_table_arns, [for arn in var.dynamodb_table_arns : "${arn}/index/*"])
  }

  dynamic "statement" {
    for_each = length(var.secret_arns) > 0 ? [1] : []
    content {
      sid       = "SecretsRead"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.secret_arns
    }
  }

  dynamic "statement" {
    for_each = var.enable_translate ? [1] : []
    content {
      sid       = "TranslateText"
      effect    = "Allow"
      actions   = ["translate:TranslateText"]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = var.enable_bedrock ? [1] : []
    content {
      sid    = "BedrockInvoke"
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ]
      resources = var.bedrock_model_arns
    }
  }

  dynamic "statement" {
    for_each = var.enable_bedrock ? [1] : []
    content {
      sid       = "BedrockGetPrompt"
      effect    = "Allow"
      actions   = ["bedrock:GetPrompt"]
      resources = ["arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:prompt/*"]
    }
  }

}

resource "aws_iam_role_policy" "app_permissions" {
  count = var.create_iam_roles ? 1 : 0

  name   = "${var.project}-app-permissions-${var.environment}"
  role   = aws_iam_role.ecs_task[0].id
  policy = data.aws_iam_policy_document.app_permissions[0].json
}
