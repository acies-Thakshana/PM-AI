variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "cors_origins" {
  description = "Browser origins allowed by the bucket's CORS rule (extra origins plus the Amplify URL)."
  type        = list(string)
}

variable "create_s3_bucket" {
  description = "true = create app data bucket; false = use existing_s3_bucket_name."
  type        = bool
}

variable "existing_s3_bucket_name" {
  description = "Existing app data S3 bucket name when create_s3_bucket=false."
  type        = string
}

variable "s3_force_destroy" {
  description = "true = `tofu destroy` also deletes every object and version in the bucket. Practice/dev only; keep false for prod. Must be applied once BEFORE the destroy."
  type        = bool
}

variable "s3_bucket_name" {
  description = "Bucket name when create_s3_bucket=true. Empty uses <project>-storage-s3-<environment>."
  type        = string
}

variable "s3_encryption_type" {
  description = "S3 server-side encryption type."
  type        = string

  validation {
    condition     = contains(["AES256", "aws:kms"], var.s3_encryption_type)
    error_message = "s3_encryption_type must be AES256 or aws:kms."
  }
}

variable "kms_key_arn" {
  description = "KMS key ARN when s3_encryption_type=aws:kms."
  type        = string
}

variable "s3_cors_max_age_seconds" {
  description = "S3 CORS max age seconds."
  type        = number
}

variable "temporary_object_expiry_days" {
  description = "Delete tmp/ objects after this many days."
  type        = number
}

variable "s3_noncurrent_version_expiry_days" {
  description = "Expire old object versions after this many days."
  type        = number
}

variable "s3_abort_multipart_days" {
  description = "Abort incomplete multipart uploads after this many days."
  type        = number
}
