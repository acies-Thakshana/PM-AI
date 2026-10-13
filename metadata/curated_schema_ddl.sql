-- Curated + NLQ operational tables (reference DDL for warehouse / DSS SQL datasets).
-- Adjust types to your dialect (Snowflake / BigQuery / Postgres / Redshift).

CREATE TABLE IF NOT EXISTS curated_cases (
  case_id            VARCHAR(64),
  customer_name      VARCHAR(255),
  plant_name         VARCHAR(255),
  priority_level     VARCHAR(64),
  case_status        VARCHAR(64),
  region             VARCHAR(64),
  opened_at          DATE,
  resolution_hours   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS curated_customers (
  customer_name      VARCHAR(255),
  region             VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS curated_products (
  product_name       VARCHAR(255),
  volume             BIGINT
);

-- Operational / audit tables (DSS managed datasets may instead be filesystem)
CREATE TABLE IF NOT EXISTS nlq_query_audit (
  event_time         TIMESTAMP,
  request_id         VARCHAR(64),
  user_id            VARCHAR(128),
  project_key        VARCHAR(64),
  environment        VARCHAR(32),
  question           VARCHAR(4000),
  question_len       INTEGER,
  intent             VARCHAR(64),
  query_status       VARCHAR(64),
  sql_query          VARCHAR(8000),
  datasets_used      VARCHAR(2000),
  columns_used       VARCHAR(2000),
  warning_count      INTEGER,
  assumption_count   INTEGER,
  answer_preview     VARCHAR(1000),
  response_json      VARCHAR(16000)
);

CREATE TABLE IF NOT EXISTS nlq_questions (
  question_id        VARCHAR(64),
  question           VARCHAR(4000),
  user_id            VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS nlq_answers (
  question_id        VARCHAR(64),
  user_id            VARCHAR(128),
  question           VARCHAR(4000),
  intent             VARCHAR(64),
  interpreted_question VARCHAR(4000),
  datasets_used      VARCHAR(2000),
  columns_used       VARCHAR(2000),
  sql_query          VARCHAR(8000),
  query_status       VARCHAR(64),
  answer             VARCHAR(8000),
  chart_spec         VARCHAR(16000),
  assumptions        VARCHAR(4000),
  warnings           VARCHAR(4000),
  response_json      VARCHAR(16000),
  created_at         TIMESTAMP
);
