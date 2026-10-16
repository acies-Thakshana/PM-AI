# Where THIS environment keeps its OpenTofu state (its memory of what it built).
#
# The key is different in every environment, so dev, uat and prod can never see or change each other's state.
#   dev  -> envs/dev/terraform.tfstate
#   uat  -> envs/uat/terraform.tfstate
#   prod -> envs/prod/terraform.tfstate
#
# For a real client rollout give each environment its OWN state bucket in its OWN account, and change
# bucket / region below. A backend block cannot use variables, so these values are written out here.
# The login comes from your terminal (for example  $env:AWS_PROFILE="rishikesh"), not from terraform.tfvars.
#
# The state bucket must exist before "tofu init" (create it once, by hand: versioning + encryption on).
# To try a folder without S3, comment this block out: the state then stays in this folder as terraform.tfstate.
terraform {
  backend "s3" {
    bucket       = "pmai-tfstate-372544872383-eu-north-1" # Acies practice state bucket
    key          = "envs/prod/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true # blocks two people applying at once (OpenTofu 1.10+)
  }
}
