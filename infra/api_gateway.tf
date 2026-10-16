# ----------------------------------------------------------------------------------------------
# API Gateway
#
# HTTP API (with CORS), VPC Link into the private network, integration to the load balancer listener,
# catch-all route and the $default stage with its access-log group.
# ----------------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${var.project}-api-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-apigw-logs-${var.environment}"
  }
}

resource "aws_apigatewayv2_api" "backend" {
  name          = "${var.project}-api-${var.environment}"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["*"]
    allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_origins     = local.cors_origins
    expose_headers    = ["*"]
    max_age           = var.api_gateway_cors_max_age_seconds
  }

  tags = {
    Name = "${var.project}-api-${var.environment}"
  }
}

resource "aws_apigatewayv2_vpc_link" "backend" {
  name               = "${var.project}-vpclink-${var.environment}"
  security_group_ids = [local.vpclink_security_group_id]
  subnet_ids         = local.private_subnet_ids

  tags = {
    Name = "${var.project}-vpclink-${var.environment}"
  }
}

resource "aws_apigatewayv2_integration" "alb" {
  api_id                 = aws_apigatewayv2_api.backend.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = aws_lb_listener.http.arn
  payload_format_version = "1.0"
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.backend.id
  timeout_milliseconds   = var.api_gateway_timeout_ms
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.backend.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.alb.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.backend.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      integrationErr = "$context.integrationErrorMessage"
    })
  }

  tags = {
    Name = "${var.project}-api-stage-${var.environment}"
  }
}
