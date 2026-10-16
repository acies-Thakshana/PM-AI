# Where THIS environment keeps its OpenTofu state (its memory of what it built).
#
# This folder holds ONE environment (UAT): one state key, selected values come from uat.tfvars.
#   uat  -> envs/uat/terraform.tfstate
#
# If you ever add another environment to this same folder, give it its OWN key/workspace, otherwise the
# environments share one state and a plan for one will try to destroy the other.
#
# For a real client rollout give each environment its OWN state bucket in its OWN account, and change
# bucket / region below. A backend block cannot use variables, so these values are written out here.
# The login comes from your terminal (for example  $env:AWS_PROFILE="rishikesh"), not from uat.tfvars.
#
# The state bucket must exist before "tofu init" (create it once, by hand: versioning + encryption on).
# To try a folder without S3, comment this block out: the state then stays in this folder as terraform.tfstate.
terraform {
  backend "s3" {
    bucket       = "" # Acies practice state bucket
    key          = "envs/uat/terraform.tfstate"
    region       = "us-east-1-1"
    encrypt      = true
    use_lockfile = true # blocks two people applying at once (OpenTofu 1.10+)
  }
}
