#!/usr/bin/env bash
# Starts (or updates) the platform. Runs at every boot (aclopi.service) and at every deployment
# (GitHub Actions -> SSM Run Command). Idempotent: running it twice leaves the same result.
#   1. re-attaches the Elastic IP (CloudFront's origin) if the instance is new;
#   2. reads the secrets and the image tag from Parameter Store and writes the .env files;
#   3. pulls the images from ECR and starts the containers.
set -euo pipefail
source /opt/aclopi/bin/common.sh
cd /opt/aclopi

# 1. Elastic IP
token="$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')"
instance_id="$(curl -fsS -H "X-aws-ec2-metadata-token: ${token}" http://169.254.169.254/latest/meta-data/instance-id)"
current="$(aws ec2 describe-addresses --region "${AWS_REGION}" --allocation-ids "${EIP_ALLOCATION}" \
  --query 'Addresses[0].InstanceId' --output text)"
if [[ "${current}" != "${instance_id}" ]]; then
  log "associating the Elastic IP with ${instance_id} (was ${current})"
  aws ec2 associate-address --region "${AWS_REGION}" --allocation-id "${EIP_ALLOCATION}" \
    --instance-id "${instance_id}" --allow-reassociation >/dev/null
fi

# 2. Settings and secrets (files readable by root only)
image_tag="$(param deploy/image_tag 2>/dev/null || echo "${DEFAULT_IMAGE_TAG}")"
umask 077
cat > .env <<EOF
AWS_REGION=${AWS_REGION}
IMAGE_TAG=${image_tag}
PLATFORM_IMAGE=${PLATFORM_IMAGE}
AGENT_IMAGE=${AGENT_IMAGE}
TABLE_PREFIX=${TABLE_PREFIX}
LOG_GROUP_PLATFORM=${LOG_GROUP_PLATFORM}
LOG_GROUP_AGENT=${LOG_GROUP_AGENT}
LLM_HOSTNAME=${LLM_HOSTNAME}
LLM_PORT=${LLM_PORT}
LLM_IP=$(param llm/host_ip)
AGENT_TOKEN=$(param_secure app/agent_token)
ORIGIN_VERIFY=$(param_secure app/origin_verify)
EOF
{
  echo "ACLOPI_LLM_API_KEY=$(param_secure llm/api_key)"
  anthropic="$(param_secure llm/anthropic_api_key 2>/dev/null || true)"
  [[ -n "${anthropic}" && "${anthropic}" != "none" ]] && echo "ANTHROPIC_API_KEY=${anthropic}"
} > agent.secrets.env
umask 022
mkdir -p results/agent && chown -R 1000:1000 results

# 3. Images and containers
aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}" >/dev/null
log "pulling images with tag ${image_tag}"
docker compose pull --quiet
docker compose up -d --remove-orphans
docker image prune -f >/dev/null
log "platform started (tag ${image_tag})"
