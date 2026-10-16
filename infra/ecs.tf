# ----------------------------------------------------------------------------------------------
# ECS
#
# The container's environment variables, log group, cluster, task definition and service.
# ----------------------------------------------------------------------------------------------

locals {
  # Names below are the ones the backend reads (backend/app/config.py, deploy/taskdef.json).
  # DDB_DOCS switches the backend to AWS storage (S3_BUCKET only holds the downloadable files);
  # without it the backend falls back to local files.
  ecs_environment = concat([
    { name = "CORS_ORIGINS", value = join(",", local.cors_origins) },
    { name = "BEDROCK_PROMPT_IDS", value = jsonencode(var.bedrock_prompt_ids) },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "TRANSLATE_REGION", value = var.aws_region },
    { name = "S3_BUCKET", value = local.s3_bucket_name },
    { name = "DDB_DOCS", value = lookup(local.dynamodb_table_names, "docs", "") },
    { name = "DDB_PROFILES", value = lookup(local.dynamodb_table_names, "profiles", "") },
    { name = "DDB_AUDIT", value = lookup(local.dynamodb_table_names, "audit_log", "") }
    ], var.enable_bedrock ? [
    { name = "BEDROCK_REGION", value = var.aws_region },
    { name = "BEDROCK_CHEAP_MODEL", value = var.bedrock_cheap_model_id },
    { name = "BEDROCK_DEFAULT_MODEL", value = var.bedrock_default_model_id },
    { name = "BEDROCK_STRONG_MODEL", value = var.bedrock_strong_model_id }
    ] : [],
    var.allow_anon ? [{ name = "ALLOW_ANON", value = "1" }] : [],
    var.entra_tenant_id != "" && var.entra_client_id != "" ? [
      { name = "ENTRA_TENANT_ID", value = var.entra_tenant_id },
      { name = "ENTRA_CLIENT_ID", value = var.entra_client_id }
  ] : [])
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project}-task-ecs-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-ecs-logs-${var.environment}"
  }
}

resource "aws_ecs_cluster" "backend" {
  name = "${var.project}-ecs-${var.environment}"

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = {
    Name = "${var.project}-ecs-${var.environment}"
  }
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project}-task-ecs-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.ecs_cpu)
  memory                   = tostring(var.ecs_memory)
  execution_role_arn       = local.ecs_execution_role_arn
  task_role_arn            = local.ecs_task_role_arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = "${local.ecr_repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = local.ecs_environment
      secrets     = local.ecs_container_secrets

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project}-task-ecs-${var.environment}"
  }
}

resource "aws_ecs_service" "backend" {
  name            = "${var.project}-service-ecs-${var.environment}"
  cluster         = aws_ecs_cluster.backend.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = local.private_subnet_ids
    security_groups  = [local.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = var.container_port
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy_attachment.ecs_execution_managed # ECS must not start before the role can pull images
  ]

  tags = {
    Name = "${var.project}-service-ecs-${var.environment}"
  }
}
