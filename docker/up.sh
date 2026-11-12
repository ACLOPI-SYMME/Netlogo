#!/usr/bin/env sh
# Start the local stack (docs/deploy-local.md) with Linea A's real agent (default) or the mock agent (tests only).
#   docker/up.sh              real agent (profile "agent", image rebuilt so it has the current code)
#   docker/up.sh --agent mock mock agent (profile "mock"), only for automatic tests
# The other agent is removed first if it was left running. ACLOPI_AGENT_URL is set for these commands only,
# so the platform always talks to the agent that was started: it is not read from .env.
# Stop everything with docker/down.sh.
set -e
cd "$(dirname "$0")/.."
agent=real
if [ "$1" = "--agent" ]; then agent="$2"; fi
case "$agent" in
  real)
    docker compose --profile mock rm --stop --force agent-mock
    ACLOPI_AGENT_URL=http://agent:8100 docker compose --profile agent up -d --build ;;
  mock)
    docker compose --profile agent rm --stop --force agent
    ACLOPI_AGENT_URL=http://agent-mock:8100 docker compose --profile mock up -d --build ;;
  *)
    echo "usage: docker/up.sh [--agent real|mock]" >&2; exit 2 ;;
esac
echo "Stack up with the $agent agent. /health shows it under 'agent' (kind, url); stop it with docker/down.sh"
