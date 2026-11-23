#!/usr/bin/env bash
# Loads the platform's secrets and settings into AWS Parameter Store (infra/README.md, step 4).
# Run it BEFORE the first `terraform apply` (CloudFront reads /aclopi/app/origin_verify) and again whenever a value
# changes (then restart the platform: re-run the deployment, or reboot the instance).
# Values are typed here and go straight to AWS: they are never written to disk or to git.
#
#   AWS_PROFILE=<your profile> bash scripts/aws/put-secrets.sh
# Requires: aws CLI v2 logged into the account, openssl.
set -euo pipefail

REGION="${AWS_REGION:-eu-north-1}"
PREFIX="/aclopi"

put() {  # put <name> <type> <value>
  aws ssm put-parameter --region "$REGION" --name "$PREFIX/$1" --type "$2" --value "$3" --overwrite >/dev/null
  echo "  saved $PREFIX/$1 ($2)"
}

exists() { aws ssm get-parameter --region "$REGION" --name "$PREFIX/$1" >/dev/null 2>&1; }

ask() {  # ask <prompt> [secret]
  local value
  if [[ "${2:-}" == "secret" ]]; then read -r -s -p "$1: " value; echo >&2; else read -r -p "$1: " value; fi
  echo "$value"
}

echo "Account: $(aws sts get-caller-identity --query Account --output text)  Region: $REGION"
echo

echo "University VPN (Cisco Secure Client)"
put vpn/server   String       "$(ask '  VPN server address (as in Cisco Secure Client)')"
put vpn/user     String       "$(ask '  VPN user')"
put vpn/password SecureString "$(ask '  VPN password' secret)"
echo

echo "LLM (Strata)"
echo "  IP of coretex.local.univ-savoie.fr: with the VPN on, run: nslookup coretex.local.univ-savoie.fr"
put llm/host_ip  String       "$(ask '  LLM server IP')"
put llm/api_key  SecureString "$(ask '  Strata API key' secret)"
anthropic="$(ask '  Anthropic API key for the fallback (Enter to skip)' secret)"
put llm/anthropic_api_key SecureString "${anthropic:-none}"
echo

echo "Internal secrets (generated; existing ones are kept so running services do not break)"
for name in app/agent_token app/origin_verify; do
  if exists "$name" && [[ "${ROTATE:-}" != "1" ]]; then
    echo "  kept $PREFIX/$name (ROTATE=1 to generate a new one)"
  else
    put "$name" SecureString "$(openssl rand -hex 32)"
  fi
done

if ! exists deploy/image_tag; then
  put deploy/image_tag String latest
fi

echo
echo "Done. If you changed app/origin_verify, run terraform apply (CloudFront) and restart the platform."
