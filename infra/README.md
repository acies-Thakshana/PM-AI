# PMAI infrastructure (OpenTofu): one folder per environment, shared modules

```text
Amplify frontend -> API Gateway -> VPC Link -> internal ALB -> ECS Fargate backend -> S3, DynamoDB, Bedrock, Translate
```

## Folder layout

```text
infra/
├── envs/                      one folder per environment = one working directory = one state
│   ├── dev/
│   │   ├── backend.tf         WHERE this environment's state lives (differs per env: the key)
│   │   ├── main.tf            calls the modules (IDENTICAL in dev, uat, prod)
│   │   ├── providers.tf       OpenTofu + AWS provider settings (identical)
│   │   ├── variables.tf       every input the environment accepts (identical)
│   │   ├── outputs.tf         values printed after apply (identical)
│   │   └── terraform.tfvars   THE VALUES for this environment (differs per env)
│   ├── uat/   (same six files)
│   └── prod/  (same six files)
├── modules/                   the real code, written once and reused by every environment
│   ├── network/    VPC, subnets, internet gateway, NAT, route tables, S3/DynamoDB endpoints
│   ├── security/   the three chained firewalls (security groups)
│   ├── registry/   ECR repository + clean-up policy
│   ├── secrets/    legacy API-key containers (switched off today)
│   ├── storage/    S3 data bucket and its settings
│   ├── database/   the four DynamoDB tables
│   ├── iam/        execution role + task role and their permissions
│   ├── compute/    internal load balancer + ECS (cluster, task definition, service)
│   ├── api/        API Gateway, VPC Link, route, stage
│   └── frontend/   Amplify app + branch
├── templates/
│   └── cg-existing-vpc.tfvars.example   values for a client that supplies its own VPC (not used directly)
├── VALUES_TO_FILL.md
└── README.md
```

Each module has exactly three files: `main.tf` (the resources), `variables.tf` (its inputs), `outputs.tf` (what it hands back).

## How to use an environment

Run every command from inside that environment's folder.

```powershell
cd infra\envs\dev
$env:AWS_PROFILE="rishikesh"                      # your AWS login (the state backend reads this)
$env:TF_VAR_amplify_access_token="<github token>" # never put the token in a file

$env:TF_VAR_image_tag="1.1.0"                   # the image tag you pushed: NOT stored in terraform.tfvars

tofu init        # first time per folder: downloads the provider, connects to the state
tofu validate
tofu plan        # read it carefully
tofu apply
```

`image_tag` is the one value that is **not** in `terraform.tfvars` and has no default. It changes with every
release, so it is supplied when you run: `$env:TF_VAR_image_tag="<version>"` (as above) or
`tofu apply -var "image_tag=<version>"`. A pipeline passes the commit or release tag the same way. It must
equal the tag you pushed to ECR. `plan`, `apply` and `destroy` all need a value (any text works for `destroy`).

There is **no `-var-file` flag any more**: OpenTofu loads `terraform.tfvars` from the folder by itself.

Before the first `init` the state bucket named in `backend.tf` must exist (create it once, by hand, with
versioning and encryption on). To try a folder without S3, comment out the block in `backend.tf`; the state
then stays in that folder.

## Why this fixes the state problem

| Before (one folder, several tfvars) | Now |
|---|---|
| One state shared by every environment | One state per folder (the `key` in `backend.tf` is different) |
| You had to switch with `init -reconfigure` | You `cd` into the environment. The folder IS the environment. |
| A wrong `-var-file` could plan to destroy dev | `plan` in `envs/uat` cannot read dev's state |

## What must stay identical, and what may differ

| File | dev / uat / prod |
|---|---|
| `main.tf`, `providers.tf`, `variables.tf`, `outputs.tf` | **Identical.** Check with: `Compare-Object (Get-Content envs\dev\main.tf) (Get-Content envs\uat\main.tf)` (no output = identical) |
| `backend.tf` | Same except the state `key` (and, for a real rollout, the bucket and region) |
| `terraform.tfvars` | The only place the environments differ: names, sizes, ids, flags |

## Adding a new environment

1. Copy an existing folder: `Copy-Item envs\uat envs\staging -Recurse`
2. In `envs\staging\backend.tf` change the state `key` to `envs/staging/terraform.tfstate`.
3. In `envs\staging\terraform.tfvars` set `environment = "staging"` and review every `REVIEW` line.
4. `cd envs\staging`, then `tofu init`, `tofu plan`.

## Naming

Every resource is named `<project>-<thing>-<environment>`; with `project = "uda327"` that gives names such as
`uda327-alb-dev`, `uda327-alb-uat`, `uda327-alb-prod`. The names live inside the modules, so they are the same
in every environment and only `project` and `environment` (in `terraform.tfvars`) change.

| Resource | Name (dev shown) |
|---|---|
| Security groups | `uda327-vpclink-sg-dev`, `uda327-alb-sg-dev`, `uda327-ecs-sg-dev` |
| ECR repository | `uda327-backend-dev` |
| IAM roles | `uda327-ecs-execution-role-dev`, `uda327-ecs-task-role-dev` |
| S3 bucket | `uda327-storage-s3-dev` |
| DynamoDB tables | `uda327-records-dynamodb-dev`, `uda327-profiles-dynamodb-dev`, `uda327-events-dynamodb-dev`, `uda327-chats-dynamodb-dev` |
| Load balancer, target group | `uda327-alb-dev`, `uda327-alb-tg-dev` |
| ECS cluster, task definition, service | `uda327-ecs-dev`, `uda327-task-ecs-dev`, `uda327-service-ecs-dev` |
| API Gateway, VPC Link, stage label | `uda327-api-dev`, `uda327-vpclink-dev`, `uda327-api-stage-dev` |
| Amplify app | `uda327-frontend-dev` |

The code creates exactly **one** S3 bucket per environment (`uda327-storage-s3-<environment>`). The OpenTofu
state bucket named in `backend.tf` is separate: it is created by hand and is not part of the modules.

One name can be set by hand when a client's naming differs from the pattern: `ecr_repository_name` (ECR; UAT uses
`uda327-backend-ecr-uat`). The DynamoDB names follow `<project>-<records|profiles|events>-dynamodb-<environment>`,
fixed inside `modules/database/main.tf` (there is no per-environment override).
An S3 bucket name must be unique across all of AWS. If `uda327-storage-s3-dev` is taken, set `s3_bucket_name`.

## Notes

- `envs/uat` and `envs/prod` currently hold a **copy of the dev values** with the environment name changed (UAT also carries its naming-sheet names). They are
  a starting point; lines marked `REVIEW` must be checked before real use (for example `ecr_force_delete`,
  `allow_anon`, `bedrock_model_arns`, the prompt ids, and the ECR repository name if two environments share
  one AWS account).
- Prompt ids (`bedrock_prompt_ids`) belong to an AWS account and region. Create them in each environment's
  account.
- `required_version` is `>= 1.10.0` because the S3 state lock file (`use_lockfile`) needs OpenTofu 1.10+.
- The old flat layout is saved in git commit `439ddab` and in a copy outside the repository.
