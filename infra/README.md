# PMAI infrastructure (OpenTofu): flat layout, one folder, UAT

```text
Amplify frontend -> API Gateway -> VPC Link -> internal ALB -> ECS Fargate backend -> S3, DynamoDB, Bedrock, Translate
```

This branch (`infra-flat-layout`) has **no modules and no per-environment folders**. All resources are written
directly in the files below, with a single `variables.tf`. The values for UAT are in `uat.tfvars`.

## Files

```text
infra/
├── backend.tf          where the state lives (S3 bucket, key envs/uat/terraform.tfstate)
├── providers.tf        OpenTofu version, AWS provider, default_tags
├── variables.tf        ONE variables file: every input
├── locals.tf           name prefix, common tags, cors_origins
├── outputs.tf          API URL, ECR URL, bucket, tables, ...
│
├── network.tf          VPC, subnets, internet gateway, NAT, route tables, S3/DynamoDB endpoints
├── security_groups.tf  vpclink-sg -> alb-sg -> ecs-sg
├── ecr.tf              ECR repository + clean-up policy
├── secrets.tf          legacy API-key containers (switched off)
├── storage.tf          S3 data bucket + the three DynamoDB tables
├── iam.tf              execution role + task role
├── load_balancer.tf    internal ALB, target group, listener
├── ecs.tf              container environment, log group, cluster, task definition, service
├── api_gateway.tf      HTTP API, VPC Link, route, stage
├── amplify.tf          Amplify app + branch
│
├── uat.tfvars          the UAT values
├── templates/          values for a client that supplies its own VPC (not used directly)
└── VALUES_TO_FILL.md
```

Variable flow (one layer): `uat.tfvars` -> `variables.tf` -> `var.xxx` inside the resource files.
Values shared between files (VPC id, bucket name, role ARNs, ...) are `local.xxx` values.

## How to run

```powershell
cd infra
$env:AWS_PROFILE="<profile>"
$env:TF_VAR_amplify_access_token="<github token>"   # never put the token in a file
$env:TF_VAR_image_tag="1.0.0"                       # the tag you pushed to ECR; not stored in uat.tfvars

tofu init
tofu validate
tofu plan  -var-file="uat.tfvars"
tofu apply -var-file="uat.tfvars"
```

`-var-file="uat.tfvars"` is required here (the file is not named `terraform.tfvars`, so it is not loaded automatically).

## Naming

Resources are named `<project>-<thing>-<environment>` (for example `uda327-alb-uat`). DynamoDB tables are
`uda327-<records|profiles|events>-dynamodb-uat` (pattern set in `storage.tf`). The ECR name is set with
`ecr_repository_name` (`uda327-backend-ecr-uat`).

## Trade-off of this layout

One folder = one state. This folder is meant for UAT only. Do not apply a different environment's values to
it (for example a `dev.tfvars`) without a separate state key or workspace, or OpenTofu will plan to destroy
the other environment's resources. The previous `envs/` + `modules/` layout is on branch
`enhanced-with-agents-infra`.
