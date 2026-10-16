# ----------------------------------------------------------------------------------------------
# Module: storage
#
# The S3 data bucket and all of its settings: public-access block, versioning, encryption, CORS,
# lifecycle rules and the 'HTTPS only' bucket policy.
#
# With create_s3_bucket = false the client's bucket name is used instead.
# Moved unchanged from the S3 half of storage.tf; only local.cors_origins became var.cors_origins.
# ----------------------------------------------------------------------------------------------

locals {
  # S3 selection.
  generated_s3_bucket_name = "${var.project}-storage-s3-${var.environment}"
  s3_bucket_name           = var.create_s3_bucket ? (var.s3_bucket_name != "" ? var.s3_bucket_name : local.generated_s3_bucket_name) : var.existing_s3_bucket_name
  s3_bucket_arn            = "arn:aws:s3:::${local.s3_bucket_name}"
}

resource "aws_s3_bucket" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket        = local.s3_bucket_name
  force_destroy = var.s3_force_destroy

  tags = {
    Name = "${var.project}-storage-s3-${var.environment}"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.s3_encryption_type
      kms_master_key_id = var.s3_encryption_type == "aws:kms" ? var.kms_key_arn : null
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "data" {
  # An S3 CORS rule needs at least one origin, so skip it when there is none.
  count = var.create_s3_bucket && length(var.cors_origins) > 0 ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_origins = var.cors_origins
    expose_headers  = ["ETag"]
    max_age_seconds = var.s3_cors_max_age_seconds
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id

  rule {
    id     = "expire-temporary-objects"
    status = "Enabled"

    filter {
      prefix = "tmp/"
    }

    expiration {
      days = var.temporary_object_expiry_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = var.s3_abort_multipart_days
    }
  }

  rule {
    id     = "expire-old-object-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = var.s3_noncurrent_version_expiry_days
    }
  }
}

data "aws_iam_policy_document" "data_bucket" {
  count = var.create_s3_bucket ? 1 : 0

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      local.s3_bucket_arn,
      "${local.s3_bucket_arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  count = var.create_s3_bucket ? 1 : 0

  bucket = aws_s3_bucket.data[0].id
  policy = data.aws_iam_policy_document.data_bucket[0].json
}
