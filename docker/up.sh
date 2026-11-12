#!/usr/bin/env sh
# Start the local stack (docs/deploy-local.md) with the mock agent (default) or Linea A's real agent.
#   docker/up.sh              mock agent (agent-mock)
#   docker/up.sh --agent real real agent (profile "agent", image rebuilt so it has the current code)
# ACLOPI_AGENT_URL is set for these commands only, so the platform always talks to the agent that was
# started: it is not read from .env. Stop everything with docker/down.sh.
set -e
cd "$(dirname "$0")/.."
agent=mock
if [ "$1" = "--agent" ]; then agent="$2"; fi
case "$agent" in
  real)
    ACLOPI_AGENT_URL=http://agent:8100 docker compose --profile agent up -d --build ;;
  mock)
    docker compose --profile agent rm --stop --force agent  # a real agent left from an earlier start
    ACLOPI_AGENT_URL=http://agent-mock:8100 docker compose up -d --build ;;
  *)
    echo "usage: docker/up.sh [--agent mock|real]" >&2; exit 2 ;;
esac
echo "Stack up with the $agent agent. /health shows it under 'agent' (kind, url); stop it with docker/down.sh"
