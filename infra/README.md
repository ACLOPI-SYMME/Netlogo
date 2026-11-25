# AWS deployment

Terraform for the cloud platform: one EC2 instance (`m7i-flex.large` on the AWS Free plan, Ubuntu 26.04) with the platform and the agent in
Docker, behind CloudFront, in Stockholm (`eu-north-1`). Design and decisions: project document
"Contexto Línea B - Arquitectura Cloud", sections 0, 0.1 and 0.2.

```
users ──HTTPS/WSS──► CloudFront (https://<id>.cloudfront.net)
                       ├─ everything (/ui, API, /ws/...) ──► EC2 (Elastic IP, port 80, X-Origin-Verify header)
                       └─ 502/504 ──► S3 "platform offline" page
EC2: platform + agent (Docker) ─ VPN (openconnect, split tunnel) ─► university LLM (Strata on coretex)
     ├─► DynamoDB (aclopi_runs, aclopi_decisions, aclopi_product_sets)   ├─► CloudWatch (logs, metrics, alarms)
     └─◄ ECR (images)                                                      └─► S3 (artifacts)
```

| Piece | What it does |
|---|---|
| EC2 + EventBridge Scheduler | One instance, started and stopped on a schedule (Europe/Paris, default Mon–Fri 08:45–12:00). Stopped, it keeps its disk (image and VPN installed), so a start takes ~2–3 min. AWS automatic recovery moves it to healthy hardware if the host fails |
| Elastic IP | Fixed origin for CloudFront; stays attached while the instance is stopped |
| CloudFront | The only way in. HTTPS without our own domain, no caching, WebSockets. The security group accepts port 80 only from CloudFront and the API rejects CloudFront requests without the secret header (`aclopi/api/origin.py`) |
| VPN | `aclopi-vpn.service`: openconnect + vpn-slice; **only** the LLM server's IP goes through the tunnel. Reconnects by itself after a cut (30 s, growing to 15 min between attempts); stops on wrong settings (see Day to day) |
| Secrets | Parameter Store (`/aclopi/...`), read at every boot. Never in git, in the image or in the user data |
| Health | No load balancer: the instance publishes `PlatformReady`, `AgentUp`, `VpnUp` every minute; alarms by e-mail |

Files: `bootstrap/` (state bucket), `*.tf` (everything else), `files/` (user data, production compose, instance
scripts, offline page). Deployment workflow: `.github/workflows/deploy-aws.yml`. Secrets: `scripts/aws/put-secrets.sh`.

## First deployment

Requirements: AWS account (Free plan: defaults below; paid plan: see "Sizing"), Terraform >= 1.10,
AWS CLI v2 >= 2.32 with a profile (`aws login --profile <profile>` for project team members), Docker, `gh` (optional).

1. **vCPU quota.** Service Quotas → EC2 → "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" in
   `eu-north-1` must be ≥ 2 (≥ 4 for `m7i.xlarge`). Ask for more if not: it can take 1–2 days.
2. **Credentials.** `export AWS_PROFILE=<profile>` (PowerShell: `$env:AWS_PROFILE="<profile>"`).
3. **State bucket (once).**
   ```bash
   cd infra/bootstrap && terraform init && terraform apply     # prints state_bucket
   cd .. && cp backend.hcl.example backend.hcl                  # put the bucket name in backend.hcl
   ```
4. **Secrets.** `bash scripts/aws/put-secrets.sh` (asks for the VPN server, user and password, the optional server
   certificate pin, the LLM server IP, the Strata API key and, optionally, an Anthropic key; generates the agent token
   and the CloudFront header). In Git Bash, first `export MSYS_NO_PATHCONV=1` (otherwise it turns `/aclopi/...` into a
   Windows path).
5. **ECR first, then the images.** The instance pulls `latest` on its first boot, so the images must exist before it:
   ```bash
   cp terraform.tfvars.example terraform.tfvars                 # set alert_email
   terraform init -backend-config=backend.hcl
   terraform apply -target=aws_ecr_repository.app
   ```
   Push the images: run the workflow (step 7 first) or by hand:
   ```bash
   REG=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.eu-north-1.amazonaws.com
   aws ecr get-login-password --region eu-north-1 | docker login -u AWS --password-stdin $REG
   docker build -f docker/Dockerfile -t $REG/aclopi-platform:latest . && docker push $REG/aclopi-platform:latest
   docker build -f docker/agent.Dockerfile -t $REG/aclopi-agent:latest . && docker push $REG/aclopi-agent:latest
   ```
6. **Everything else.** `terraform apply`. It prints `platform_url`. The instance starts right away and needs ~5 minutes
   the first time (packages, images, 7 NetLogo workers); until then CloudFront shows the offline page. It stays on
   until the next scheduled stop: stop it by hand when you finish checking (table below).
7. **GitHub.** `gh variable set AWS_DEPLOY_ROLE_ARN --body "$(terraform output -raw github_deploy_role_arn)"`
   (or Settings → Secrets and variables → Actions → Variables).
8. **E-mail.** Confirm the SNS subscription AWS sends to `alert_email`, or no alarm arrives.
9. **Check.** Open `platform_url`. Then measure the start time (5 stop → start cycles, from `start-instances` until
   `/health/ready` answers) and adjust `schedule_start`.

If the account already has a GitHub OIDC provider, set `create_github_oidc_provider = false`.

## Sizing

| Plan | `instance_type` | `platform_env` | Simultaneous users |
|---|---|---|---|
| Free (default) | `m7i-flex.large` (2 vCPU / 8 GB, the largest the Free plan allows) | `ACLOPI_N_SESSION_WORKERS=2`, `ACLOPI_N_WHATIF_WORKERS=1` | 2 (more wait in the queue) |
| Paid | `m7i.xlarge` (4 vCPU / 16 GB) | `5` and `2` | 5 |

Moving between them: set both in `terraform.tfvars`, then `terraform apply -replace=aws_instance.platform`
(`platform_env` is written on the first boot). The platform container is capped at 6 GB in both cases.

## Day to day

| Task | How |
|---|---|
| Deploy a new version | Actions → **Deploy to AWS** → Run workflow (from `main`). Builds, pushes to ECR, records the tag in `/aclopi/deploy/image_tag` and restarts the containers. If the instance is off, it gets the version at its next boot |
| Change infrastructure | Edit the `.tf` → `terraform plan` → `terraform apply` → commit. The state lives in S3 with locking: no pulling or pushing it by hand. Never change resources from the console |
| Change a secret | `bash scripts/aws/put-secrets.sh`, then redeploy (or reboot). `ROTATE=1` generates new internal secrets; after rotating `origin_verify`, `terraform apply` too. One value only: `aws ssm put-parameter --name /aclopi/<name> --type String --value <value> --overwrite` |
| VPN stopped on wrong settings (`/var/log/aclopi/vpn.log`: "wrong VPN settings") | Fix the value (user, password, server or `vpn/servercert`), then on the instance: `sudo systemctl reset-failed aclopi-vpn && sudo systemctl start aclopi-vpn`. The `vpn-down` alarm reports it |
| VPN certificate changed ("Error in the certificate" in the log) | Copy the new `pin-sha256:...` that openconnect prints into `/aclopi/vpn/servercert`, then restart as above |
| Change the instance type, schedule | Variables → `terraform apply`. A new instance type stops and starts the instance (sessions in progress are lost) |
| Change the user data, the instance scripts or the settings (`agent_env`, `platform_env`) | They are written on the first boot only: `terraform apply -replace=aws_instance.platform` (new instance, ~5 min; the Elastic IP moves to it) |
| Turn it on now / off now | `aws ec2 start-instances --instance-ids $(terraform output -raw instance_id)` (or `stop-instances`). The schedule still stops it at the next stop time |
| Shell on the instance | Systems Manager → Session Manager (there is no SSH). Logs: `/var/log/aclopi/`, `docker compose -f /opt/aclopi/docker-compose.yml logs` |
| Logs and metrics | CloudWatch: log groups `/aclopi/platform`, `/aclopi/agent`, `/aclopi/system`; dashboard `aclopi` |

## Notes

- Region `eu-north-1`; schedule cron in `Europe/Paris`. Prices and sizing: project document "Presupuesto - Plataforma y Agente".
- The VPN uses personal credentials: the university has to allow it, and they must change when the internship ends.
- The CloudFront → EC2 hop is plain HTTP inside AWS (no certificate is possible for the instance's name). Users get HTTPS.
- `terraform destroy` removes everything except the state bucket and the ECR images (`force_delete = false`).
