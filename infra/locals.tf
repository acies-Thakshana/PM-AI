# ----------------------------------------------------------------------------------------------
# Locals
#
# name_prefix, the common tags and the CORS origin list shared by API Gateway, S3 and the backend.
# ----------------------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  # Only used by the name_prefix output. Resource names are built in the resource files as
  # <project>-<thing>-<environment> (for example uda327-alb-dev).
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge({
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "opentofu"
    Owner       = var.owner
    CostCenter  = var.cost_center
  }, var.additional_tags)

  # Every origin allowed to call the API (API Gateway CORS, S3 CORS and the backend's CORS_ORIGINS).
  # The list is built with a conditional on a known flag, not compact(), so its LENGTH is known at
  # plan time (the S3 CORS rule below needs that).
  cors_origins = concat(var.extra_cors_origins, var.enable_amplify ? [local.amplify_origin] : [])
}
