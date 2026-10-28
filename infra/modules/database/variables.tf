variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "create_dynamodb_tables" {
  description = "true = create app DynamoDB tables; false = use existing table names/ARNs."
  type        = bool
}

variable "dynamodb_billing_mode" {
  description = "DynamoDB billing mode."
  type        = string
}

variable "dynamodb_ttl_attribute" {
  description = "TTL attribute name. Backend writes epoch seconds here. Table keys are fixed per table in modules/database to match the backend (docs: session_id+doc; profiles: user_id+profile; audit-log: session_id+ts_event + by-user index; chats: chat_id+turn_id + by-user and by-session indexes)."
  type        = string
}

variable "existing_dynamodb_table_names" {
  description = "Existing table names when create_dynamodb_tables=false. Keys: profiles, docs, audit_log, chats."
  type        = map(string)
}

variable "existing_dynamodb_table_arns" {
  description = "Existing table ARNs when create_dynamodb_tables=false."
  type        = list(string)
}
