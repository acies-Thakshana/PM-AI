# ----------------------------------------------------------------------------------------------
# Module: security
#
# The three chained firewalls (security groups): VPC Link -> load balancer (port alb_listener_port)
# -> ECS containers (port container_port). Each only accepts traffic from the one before it.
#
# With create_security_groups = false the client's three group ids are passed through.
# Moved unchanged from security_groups.tf; only local.vpc_id became var.vpc_id.
# ----------------------------------------------------------------------------------------------

locals {
  # Security group selection.
  vpclink_security_group_id = var.create_security_groups ? aws_security_group.vpclink[0].id : var.existing_vpclink_security_group_id
  alb_security_group_id     = var.create_security_groups ? aws_security_group.alb[0].id : var.existing_alb_security_group_id
  ecs_security_group_id     = var.create_security_groups ? aws_security_group.ecs[0].id : var.existing_ecs_security_group_id
}

resource "aws_security_group" "vpclink" {
  count = var.create_security_groups ? 1 : 0

  name        = "${var.project}-vpclink-sg-${var.environment}"
  description = "API Gateway VPC Link security group"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow outbound from VPC Link"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${var.project}-vpclink-sg-${var.environment}"
  }
}

resource "aws_security_group" "alb" {
  count = var.create_security_groups ? 1 : 0

  name        = "${var.project}-alb-sg-${var.environment}"
  description = "Internal ALB security group"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTP from API Gateway VPC Link"
    from_port       = var.alb_listener_port
    to_port         = var.alb_listener_port
    protocol        = "tcp"
    security_groups = [aws_security_group.vpclink[0].id]
  }

  egress {
    description = "Allow outbound from ALB to ECS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${var.project}-alb-sg-${var.environment}"
  }
}

resource "aws_security_group" "ecs" {
  count = var.create_security_groups ? 1 : 0

  name        = "${var.project}-ecs-sg-${var.environment}"
  description = "ECS backend task security group"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Backend traffic from internal ALB"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb[0].id]
  }

  egress {
    description = "Allow backend outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = var.allowed_egress_cidrs
  }

  tags = {
    Name = "${var.project}-ecs-sg-${var.environment}"
  }
}
