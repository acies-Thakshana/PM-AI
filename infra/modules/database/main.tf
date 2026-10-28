# ----------------------------------------------------------------------------------------------
# Module: database
#
# The four DynamoDB tables the backend uses: docs (records), profiles, audit-log (events, with its by-user index)
# and chats (one item per chat turn, with its by-user and by-session indexes).
#
# With create_dynamodb_tables = false the client's table names / ARNs are used instead.
# Moved unchanged from the DynamoDB half of storage.tf (+ the table locals from locals.tf).
# ----------------------------------------------------------------------------------------------

locals {
  # Table names follow <project>-<purpose>-dynamodb-<environment> (naming sheet), for example
  # uda327-records-dynamodb-uat. To change the pattern, edit it here: it applies to every environment.
  table_names = {
    profiles  = "${var.project}-profiles-dynamodb-${var.environment}"
    docs      = "${var.project}-records-dynamodb-${var.environment}"
    audit_log = "${var.project}-events-dynamodb-${var.environment}"
    chats     = "${var.project}-chats-dynamodb-${var.environment}"
  }

  # DynamoDB names. These match the current app architecture: profiles, docs (records), audit log (events), chats.
  dynamodb_table_names = var.create_dynamodb_tables ? {
    profiles  = aws_dynamodb_table.profiles[0].name
    docs      = aws_dynamodb_table.docs[0].name
    audit_log = aws_dynamodb_table.audit_log[0].name
    chats     = aws_dynamodb_table.chats[0].name
  } : var.existing_dynamodb_table_names

  dynamodb_table_arns = var.create_dynamodb_tables ? [
    aws_dynamodb_table.profiles[0].arn,
    aws_dynamodb_table.docs[0].arn,
    aws_dynamodb_table.audit_log[0].arn,
    aws_dynamodb_table.chats[0].arn
  ] : var.existing_dynamodb_table_arns
}

# Table keys match what the backend reads and writes (backend/app/services/common/*, deploy/README.md).
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

# The chat's conversation record: one item per turn (backend/app/services/chat/chat_store.py, DDB_CHATS).
# Keys are the chat and the turn; a turn id sorts by time, so a chat's turns come back in order.
resource "aws_dynamodb_table" "chats" {
  count = var.create_dynamodb_tables ? 1 : 0

  name         = local.table_names.chats
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "chat_id"
  range_key    = "turn_id"

  attribute {
    name = "chat_id"
    type = "S"
  }

  attribute {
    name = "turn_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "started_at"
    type = "S"
  }

  # "Every turn this user made", newest last.
  global_secondary_index {
    name               = "by-user"
    projection_type    = "INCLUDE"
    non_key_attributes = ["session_id", "intent", "handled_by", "status"]

    key_schema {
      attribute_name = "user_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "started_at"
      key_type       = "RANGE"
    }
  }

  # "Every turn made on this session". A turn with no session yet has no session_id, so it is not in this index.
  global_secondary_index {
    name               = "by-session"
    projection_type    = "INCLUDE"
    non_key_attributes = ["user_id", "intent", "handled_by", "status"]

    key_schema {
      attribute_name = "session_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "started_at"
      key_type       = "RANGE"
    }
  }

  ttl {
    attribute_name = var.dynamodb_ttl_attribute
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = local.table_names.chats
  }
}
