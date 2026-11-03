# Model registry on AWS S3

Where registered models are stored. How the registry itself works (register, promote, rollback,
statuses) is in [docs/mlops/registry.md](../mlops/registry.md); this page only covers the AWS
side. Terraform: `infra/terraform/model-registry/`.

```
your laptop ──register/promote (writer key)──> S3 bucket smokesense-models-<account id>
     │                                              ▲
     └── model_versions row ──> Neon <──────────────┼── staging loads production model (reader key)
```

The archive lives in S3; the record of which version is `production` lives in Neon. Your laptop
and staging must use the **same Neon database**, or staging never sees what you registered.

## What Terraform creates

| Resource | Notes |
|---|---|
| S3 bucket `smokesense-models-<account id>` | public access blocked, SSE-S3 encryption, TLS-only policy, no versioning |
| IAM user `smokesense-registry-writer` | `s3:PutObject` + `s3:GetObject` on `models/*` (promote and rollback download to verify the checksum) |
| IAM user `smokesense-registry-reader` | `s3:GetObject` on `models/*` |
| Budget `smokesense-monthly` | **whole account**, default $20/month, alerts at 50% and 80% actual and 100% forecast |

Expected cost: cents per month for S3 (see the estimate in the PR/chat: small archives, a few
hundred MB at most). The budget is mostly there for the Lightsail VM (~$10-13).

## Setup

1. AWS credentials in your shell that can create S3 buckets, IAM users and budgets.
2. Create everything (state is local and gitignored; keep `terraform.tfstate`):
   ```bash
   cd infra/terraform/model-registry
   terraform init
   terraform apply -var budget_email=<your email>
   ```
3. **Create the access keys by hand**, so the secrets never enter Terraform state. Each command
   prints the key once; store it in your password manager immediately:
   ```bash
   aws iam create-access-key --user-name smokesense-registry-writer   # your laptop only
   aws iam create-access-key --user-name smokesense-registry-reader   # staging box only
   ```
4. Confirm the budget alert subscription email from AWS if it asks.

## Registering a model (laptop)

From `backend/`, with the writer key. `DATABASE_URL` is the Neon **direct** URL staging uses.

```bash
export DATABASE_URL='<neon direct url>'
export REGISTRY_BACKEND=s3
export REGISTRY_S3_BUCKET=smokesense-models-<account id>
export AWS_ACCESS_KEY_ID=<writer key id>
export AWS_SECRET_ACCESS_KEY=<writer secret>

python -m mlops.registry register data/models/baseline_v3 --name baseline --version v3 --notes "..."
python -m mlops.registry list --name baseline        # shows v3 as shadow
python -m mlops.registry promote baseline/v3         # only now is it the serving version
```

## Staging

Once inference loads models from the registry (ML-04), add to `/opt/smokesense/.env` on the box
and re-run the deploy (the stack already reads this file):

```
REGISTRY_BACKEND=s3
REGISTRY_S3_BUCKET=smokesense-models-<account id>
AWS_ACCESS_KEY_ID=<reader key id>
AWS_SECRET_ACCESS_KEY=<reader secret>
```

Never put the writer key on the box.

## Rotating or revoking a key

```bash
aws iam list-access-keys --user-name smokesense-registry-reader
aws iam create-access-key --user-name smokesense-registry-reader      # new one first
# update the box .env, redeploy, then:
aws iam delete-access-key --user-name smokesense-registry-reader --access-key-id <old id>
```
