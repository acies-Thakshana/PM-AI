# ----------------------------------------------------------------------------------------------
# Amplify
#
# Amplify app and branch. The API URL is set on the BRANCH (not the app) to avoid a circular dependency.
# ----------------------------------------------------------------------------------------------

locals {
  # Frontend origin, worked out from the Amplify app itself, so nobody types it into tfvars.
  # The Amplify app's default_domain exists as soon as the app is created (no build needed), and
  # a branch is served at https://<branch>.<default_domain> (a "/" in the branch name becomes "-").
  amplify_origin = var.enable_amplify ? "https://${replace(var.amplify_branch_name, "/", "-")}.${aws_amplify_app.frontend[0].default_domain}" : ""
}

resource "aws_amplify_app" "frontend" {
  count = var.enable_amplify ? 1 : 0

  name         = "${var.project}-frontend-${var.environment}"
  repository   = var.amplify_repository_url
  access_token = var.amplify_access_token != "" ? var.amplify_access_token : null

  platform = "WEB"

  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: frontend
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: dist
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
  YAML

  # VITE_API_BASE_URL is deliberately NOT set on the app. The API's CORS list needs this app's
  # default_domain, and the API URL would need the API, which would be a loop (app -> API -> app).
  # The variable is set on the BRANCH below instead, and a branch variable is what the build uses.
  environment_variables = {
    AMPLIFY_MONOREPO_APP_ROOT = "frontend"
  }

  tags = {
    Name = "${var.project}-frontend-${var.environment}"
  }
}

resource "aws_amplify_branch" "frontend" {
  count = var.enable_amplify ? 1 : 0

  app_id      = aws_amplify_app.frontend[0].id
  branch_name = var.amplify_branch_name

  framework = "React"
  stage     = upper(var.environment) == "PROD" ? "PRODUCTION" : "DEVELOPMENT"

  environment_variables = {
    VITE_API_BASE_URL = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
  }

  tags = {
    Name = "${var.project}-frontend-${var.environment}-${var.amplify_branch_name}"
  }
}
