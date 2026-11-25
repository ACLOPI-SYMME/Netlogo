#!/usr/bin/env bash
# University VPN (Cisco AnyConnect) with split tunnel: ONLY the LLM server's IP goes through the tunnel.
# Run by aclopi-vpn.service. Credentials from Parameter Store, never on disk.
# With the default route through the VPN, CloudFront's replies, ECR, SSM and CloudWatch would break.
#
# Exit codes: openconnect's own (the service retries with a growing delay: connection lost, server unreachable)
# or 3 = wrong settings (bad login, bad server address, server certificate does not match the pin). The service
# does NOT retry on 3, so a wrong password does not hit the university's server every few seconds (24 Nov: the
# instance's IP got blocked). After fixing the values: sudo systemctl reset-failed aclopi-vpn && sudo systemctl start aclopi-vpn
set -uo pipefail
source /opt/aclopi/bin/common.sh

CONFIG_ERROR=3

# Accept "vpn.example.org", "https://vpn.example.org/" or "http://vpn.example.org/": openconnect wants https.
server="$(param vpn/server)" || exit 1
server="${server#http://}"
server="${server#https://}"
server="https://${server%/}"
user="$(param vpn/user)" || exit 1
llm_ip="$(param llm/host_ip)" || exit 1

# Optional pin of the server certificate (pin-sha256:...), for servers whose certificate chain Ubuntu cannot
# verify. openconnect prints the value to use when it fails. "none" or missing = normal verification.
pin="$(param vpn/servercert 2>/dev/null || true)"
cert_args=()
if [[ -n "$pin" && "$pin" != "none" ]]; then
  cert_args=(--servercert "$pin")
fi

# The LLM server's name for tools on the host (the containers get it through extra_hosts).
sed -i "/[[:space:]]${LLM_HOSTNAME}\$/d" /etc/hosts
echo "${llm_ip} ${LLM_HOSTNAME}" >> /etc/hosts

log "connecting to ${server} as ${user}; split tunnel to ${llm_ip}/32; certificate pin: ${pin:-none}"
out="$(mktemp)"
param_secure vpn/password | openconnect \
  --protocol=anyconnect \
  --user="${user}" \
  --passwd-on-stdin \
  --non-inter \
  "${cert_args[@]}" \
  --script="/usr/local/bin/vpn-slice ${llm_ip}/32" \
  "${server}" 2>&1 | tee "$out"
status=${PIPESTATUS[1]}

# Errors that retrying cannot fix (patterns from openconnect's messages; the growing delay of the service is the
# backstop if a message is not recognised).
if grep -qiE 'login failed|authentication failed|invalid (user|password|credentials)|only https:// permitted|error in the certificate' "$out"; then
  log "openconnect exited with ${status}: wrong VPN settings (see above). Not retrying until the service is restarted by hand"
  rm -f "$out"
  exit "$CONFIG_ERROR"
fi
rm -f "$out"
log "openconnect exited with ${status}; the service retries"
exit "$status"
