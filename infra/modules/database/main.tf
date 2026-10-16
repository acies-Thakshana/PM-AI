# ----------------------------------------------------------------------------------------------
# Module: database
#
# The four DynamoDB tables the backend uses: sessions, profiles, docs and audit-log (with its by-user index).
#
# With create_dynamodb_tables = false the client's table names / ARNs are used instead.
# Moved unchanged from the DynamoDB half of storage.tf (+ the table locals from locals.tf).
# ----------------------------------------------------------------------------------------------

locals {
  # Table names follow <project>-<purpose>-<environment>. Any single name can be replaced through
  # var.dynamodb_table_name_overrides (keys: sessions, profiles, docs, audit_log).
  table_names = {
    sessions  = lookup(var.dynamodb_table_name_overrides, "sessions", "${var.project}-sessions-${var.environment}")
    profiles  = lookup(var.dynamodb_table_name_overrides, "profiles", "${var.project}-profiles-${var.environment}")
    docs      = lookup(var.dynamodb_table_name_overrides, "docs", "${var.project}-records-${var.environment}")
    audit_log = lookup(var.dynamodb_table_name_overrides, "audit_log", "${var.project}-events-${var.environment}")
  }

  # DynamoDB names. These match the current app architecture: sessions, profiles, docs, audit log.
  dynamodb_table_names = var.create_dynamodb_tables ? {
    sessions  = aws_dynamodb_table.sessions[0].name
    profiles  = aws_dynamodb_table.profiles[0].name
    docs      = aws_dynamodb_table.docs[0].name
    audit_log = aws_dynamodb_table.audit_log[0].name
  } : var.existing_dynamodb_table_names

  dynamodb_table_arns = var.create_dynamodb_tables ? [
    aws_dynamodb_table.sessions[0].arn,
    aws_dynamodb_table.profiles[0].arn,
    aws_dynamodb_table.docs[0].arn,
    aws_dynamodb_table.audit_log[0].arn
  ] : var.existing_dynamodb_table_arns
}

# Table keys match what the backend reads and writes (backend/app/services/common/*, deploy/README.md).
resource "aws_dynamodb_table" "sessions" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = local.table_names.sessions
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = local.table_names.sessions
  }
}

resource "aws_dynamodb_table" "profiles" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = local.table_names.profiles
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "user_id"
  range_key    = "profile"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "profile"
    type = "S"
  }

  tags = {
    Name = local.table_names.profiles
  }
}

resource "aws_dynamodb_table" "docs" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = local.table_names.docs
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "session_id"
  range_key    = "doc"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "doc"
    type = "S"
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = local.table_names.docs
  }
}

resource "aws_dynamodb_table" "audit_log" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = local.table_names.audit_log
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "session_id"
  range_key    = "ts_event"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "ts_event"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  # "Everything this user did" lookup (audit_log.py queries IndexName="by-user").
  global_secondary_index {
    name            = "by-user"
    projection_type = "ALL"

    key_schema {
      attribute_name = "user_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "ts_event"
      key_type       = "RANGE"
    }
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  tags = {
    Name = local.table_names.audit_log
  }
}
