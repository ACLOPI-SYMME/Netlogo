#!/usr/bin/env bash
# University VPN (Cisco AnyConnect) with split tunnel: ONLY the LLM server's IP goes through the tunnel.
# Run by aclopi-vpn.service (Restart=always). Credentials from Parameter Store, never on disk.
# With the default route through the VPN, CloudFront's replies, ECR, SSM and CloudWatch would break.
set -euo pipefail
source /opt/aclopi/bin/common.sh

server="$(param vpn/server)"
user="$(param vpn/user)"
llm_ip="$(param llm/host_ip)"

# The LLM server's name for tools on the host (the containers get it through extra_hosts).
sed -i "/[[:space:]]${LLM_HOSTNAME}\$/d" /etc/hosts
echo "${llm_ip} ${LLM_HOSTNAME}" >> /etc/hosts

log "connecting to ${server} as ${user}; split tunnel to ${llm_ip}/32"
param_secure vpn/password | exec openconnect \
  --protocol=anyconnect \
  --user="${user}" \
  --passwd-on-stdin \
  --non-inter \
  --script="/usr/local/bin/vpn-slice ${llm_ip}/32" \
  "${server}"
