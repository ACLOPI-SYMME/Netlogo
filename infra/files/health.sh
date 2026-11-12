#!/usr/bin/env bash
# Every minute (aclopi-health.timer): publishes to CloudWatch whether the platform is ready, whether the agent
# answers and whether the VPN tunnel is up. Without a load balancer, the alarms read these metrics.
set -uo pipefail
source /opt/aclopi/bin/common.sh

ready=0
curl -fsS -m 5 http://127.0.0.1/health/ready >/dev/null 2>&1 && ready=1

agent=0
health="$(curl -fsS -m 5 http://127.0.0.1/health 2>/dev/null || true)"
[[ "${health}" == *'"agent":{'*'"status":"ok"'* ]] && agent=1

vpn=0
ip link show tun0 >/dev/null 2>&1 && vpn=1

aws cloudwatch put-metric-data --region "${AWS_REGION}" --namespace "ACLOPI" --metric-data \
  "MetricName=PlatformReady,Value=${ready},Unit=Count" \
  "MetricName=AgentUp,Value=${agent},Unit=Count" \
  "MetricName=VpnUp,Value=${vpn},Unit=Count" || log "put-metric-data failed"
