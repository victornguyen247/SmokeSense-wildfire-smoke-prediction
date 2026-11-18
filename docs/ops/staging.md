# Staging environment (OPS-03)

Staging is **one small always-on AWS Lightsail VM** running the compose stack in
`infra/staging/`, with Neon for Postgres/PostGIS. Merging to `prod` builds the images and
deploys them. It is deliberately not ECS/Fargate: that design cost about $90/month running
24/7, far over the team budget, and the cheaper "destroy it between uses" variant left gaps
in the ingestion time series. The box costs about $10-13/month and ingests continuously.

> **Deviation from issue #50:** the trigger is a merge to `prod` (not `dev`), and staging is a
> single VM with no high availability. A deploy restarts the containers (a few seconds of
> downtime).

```
Browser ──HTTPS──> caddy (:80/:443, Let's Encrypt on <ip>.sslip.io)
                     ├─ /api/*, /health, /docs ─> backend  (uvicorn :8000)
                     └─ everything else ────────> frontend (nginx :80)
worker (celery + embedded beat, 1 replica) ──┐
backend ─────────────────────────────────────┴─> redis (broker, in the stack) + Neon (external)
```

| What | Where |
|---|---|
| Stack, Caddyfile, deploy script | `infra/staging/` |
| VM (Terraform) | `infra/terraform/staging-vm/` |
| Workflow | `.github/workflows/deploy-staging.yml` |
| Images | `ghcr.io/<owner>/smokesense-backend` and `-frontend`, tagged with the git SHA |

The worker reuses the backend image with a different command (same dependencies), so
`worker.Dockerfile` is not used here.

## One-time setup

1. **AWS credentials on your laptop** with Lightsail permissions (for example an IAM user with
   `AmazonLightsailFullAccess`, or SSO). They are only used for `terraform apply`. CI needs no
   AWS credentials.
2. **SSH keys.** Create a deploy key and keep the private half for GitHub:
   ```bash
   ssh-keygen -t ed25519 -N "" -C smokesense-staging-deploy -f ~/.ssh/smokesense_staging_deploy
   ```
3. **Create the VM.** Confirm the plan id first (`aws lightsail get-bundles` should list a 2 GB
   plan as `small_3_0`; change `bundle_id` if not), then:
   ```bash
   cd infra/terraform/staging-vm
   terraform init
   terraform apply -var 'ssh_public_keys=["<your laptop public key>", "<contents of smokesense_staging_deploy.pub>"]'
   ```
   Note `site_address` and `public_ip` from the outputs. Terraform state is local and
   gitignored: keep `terraform.tfstate` somewhere safe.
4. **Wait ~3 minutes** for cloud-init (Docker, swap, fail2ban), then check:
   `ssh deploy@<public_ip> docker --version`.
5. **Create the app env file on the box** (secrets never go through CI):
   ```bash
   scp infra/staging/.env.example deploy@<public_ip>:/opt/smokesense/.env
   ssh deploy@<public_ip> 'chmod 600 /opt/smokesense/.env && nano /opt/smokesense/.env'
   ```
   Set `SITE_ADDRESS` to the `site_address` output, `CORS_ALLOWED_ORIGINS` to
   `https://<site_address>`, `DATABASE_URL` to the Neon **direct** (not `-pooler`) string, and the API keys.
6. **GitHub settings** (repo > Settings):
   - Environment `staging`: restrict deployment branches to `prod`.
   - Secret `STAGING_SSH_KEY`: the private key file contents.
   - Secret `STAGING_SSH_KNOWN_HOSTS`: output of `ssh-keyscan -t ed25519 <site_address>`.
   - Variable `STAGING_HOST`: the `site_address`.
7. Merge to `prod` (or see "First deploy" below).

## Deploying

Merge to `prod`: the workflow builds both images, copies the stack files to the box, runs
`deploy.sh` (pull, `alembic upgrade head`, `up -d`, wait for backend health), then smoke-tests
`https://<host>/api/v1/health` and `/` from the runner. A failed pull or migration stops before
`up`, so the previous version keeps running.

Follow logs: `ssh deploy@<host> 'cd /opt/smokesense && docker compose --env-file .env --env-file image.env logs -f --tail 100 backend worker'`

### Rollback

Actions > Deploy staging > Run workflow on `prod`, with `image_tag` set to an earlier commit
SHA whose images still exist in GHCR. It skips the build and redeploys that tag. A migration
that already ran is **not** undone, so keep migrations additive (add columns/tables first,
remove in a later release).

## Neon storage

Neon's free tier is about 0.5 GB per project and the worker ingests FIRMS, AirNow and NWS
weather continuously. Growth is already capped: the daily `ingestion.live.retention` task deletes
live rows (the ones written by live jobs) older than `LIVE_RETENTION_HOURS`, default 72, from
`observations`, `fire_detections` and `weather_observations`, and prunes `ingestion_runs` after 90
days. Historical DATA-03 rows are never deleted. Set `LIVE_RETENTION_HOURS` in the box's `.env`
to keep more, and `LIVE_RETENTION_DELETE=0` for a dry run (see `.env.example`).

1. After the first week, record the size of the largest tables (`SELECT relname,
   pg_size_pretty(pg_total_relation_size(oid)) FROM pg_class WHERE relkind='r' ORDER BY
   pg_total_relation_size(oid) DESC LIMIT 10;`) and check the total fits with the 72 h window
   plus the historical data you loaded.
2. If it will not fit, shorten `LIVE_RETENTION_HOURS` or move staging to a paid Neon plan.
3. Data that training needs must not live only in staging: live rows are deleted after the
   window. Use a separate project or branch.

## Operating notes

- **Memory:** backend and worker both import pandas/xgboost; the box has a 2 GB swapfile. Check
  `ssh deploy@<host> 'free -m; docker stats --no-stream'` after the first deploys. If services
  get OOM-killed, change `bundle_id` to the 4 GB plan.
- **Worker slot:** the worker runs one Celery slot to save memory. AirNow takes about 40-55 s
  and NWS covers ~109 stations, so a slow run can hold the slot and the next scheduled runs can
  be dropped (`expires`). Watch `ingestion_runs` for gaps. **Expect to need
  `--pool=threads --concurrency=3` once OPS-04 jobs run on this worker** (ingestion is I/O-bound;
  test it on staging first) before adding processes or upgrading the plan.
- **Deploy checks:** `deploy.sh` waits for the backend to be healthy and for a worker to answer a
  Celery ping, so a green deploy means ingestion is up too. A failed pull or migration leaves
  `image.env` on the previous tag.
- **Updates:** unattended-upgrades is on. Reboot after kernel updates (`sudo reboot`);
  containers restart on their own.
- **Secrets:** rotate by editing `/opt/smokesense/.env` on the box, then re-run the deploy.
- **TLS:** Caddy renews certificates automatically; the `caddy_data` volume must survive.
- **API mode:** `MOCK_MODE=true` serves fixtures, and the map shows its "Demo data" badge
  because `/meta` reports mock mode. `MOCK_MODE=false` serves real data from the database. Until OPS-04 writes
  forecasts, `/forecast/*` returns 503 with it off. Any "no mock data" criterion
  for staging depends on those issues, not on this deploy. The frontend image pins
  `VITE_USE_MOCKS=false`, so the browser never mocks the API itself.
- **Port 22** is open to the internet because GitHub runners have no fixed IPs. Login is key-only
  and fail2ban is on. Narrow `ssh_allowed_cidrs` if you stop using CI deploys.

## First deploy from a branch

The workflow only runs for `prod`. To exercise the box before merging, deploy by hand:
`scp infra/staging/{docker-compose.yml,Caddyfile,deploy.sh} deploy@<host>:/opt/smokesense/`, build and
push the images from your machine, then `ssh deploy@<host> bash /opt/smokesense/deploy.sh <image repo> <tag>`.
