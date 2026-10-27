variable "project" {
  description = "Short project name used in resource names (for example uda327)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, uat or prod). It ends every resource name, for example uda327-alb-dev."
  type        = string
}

variable "create_placeholder_secrets" {
  description = "true = create empty secret containers. Secret VALUES must be inserted separately, not in OpenTofu."
  type        = bool
}

variable "enable_openrouter" {
  description = "Enable OpenRouter secret/env wiring. Set false if Bedrock fully replaces OpenRouter."
  type        = bool
}

variable "openrouter_secret_arn" {
  description = "Existing OpenRouter secret ARN when create_placeholder_secrets=false."
  type        = string
}

variable "enable_deepl" {
  description = "Enable DeepL secret/env wiring. Set false if Amazon Translate replaces DeepL."
  type        = bool
}

variable "deepl_secret_arn" {
  description = "Existing DeepL secret ARN when enable_deepl=true and create_placeholder_secrets=false."
  type        = string
}

variable "enable_swp" {
  description = "Create the SensiWatch (SWP) secret and hand its values to the container as environment variables."
  type        = bool
  default     = false
}

variable "swp_secret_keys" {
  description = "Keys inside the one SWP secret (a JSON text). Each key becomes an environment variable of the same name in the container. Every key listed here must exist in the secret, or the container does not start."
  type        = list(string)
  default     = ["SWP_BASE_URL", "SWP_PROGRAM_ID", "SWP_SECURITY_KEY", "SWP_TRIP_KEY", "SWP_USER", "SWP_PASS"]
}
