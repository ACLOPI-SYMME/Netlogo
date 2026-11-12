variable "project" {
  description = "Prefix of every resource name"
  type        = string
  default     = "aclopi"
}

variable "region" {
  description = "AWS region (decided 3 Nov: Stockholm)"
  type        = string
  default     = "eu-north-1"
}

# ----- compute -----

variable "instance_type" {
  description = "m7i.xlarge (4 vCPU / 16 GB). Next step if CPU falls short: m7a.xlarge (4 physical cores)"
  type        = string
  default     = "m7i.xlarge"
}

variable "ami_name_filter" {
  description = "Canonical's standard Ubuntu 26.04 image (never 'ubuntu-pro', which costs more)"
  type        = string
  default     = "ubuntu/images/hvm-ssd-gp3/ubuntu-*-26.04-amd64-server-*"
}

variable "root_volume_gb" {
  type    = number
  default = 30
}

variable "initial_capacity" {
  description = "Instances right after the first apply (0 or 1). Afterwards the schedule decides; Terraform ignores changes"
  type        = number
  default     = 1
}

variable "schedule_timezone" {
  type    = string
  default = "Europe/Paris"
}

variable "schedule_start" {
  description = "Cron (in schedule_timezone) that turns the platform on. Section 0 of the Línea B context: start >= 10 min before the users"
  type        = string
  default     = "30 7 * * 1-5"
}

variable "schedule_stop" {
  description = "Cron (in schedule_timezone) that turns the platform off"
  type        = string
  default     = "0 19 * * 1-5"
}

# ----- application -----

variable "image_tag" {
  description = "Image tag deployed on first boot. Later deployments write /aclopi/deploy/image_tag (GitHub Actions)"
  type        = string
  default     = "latest"
}

variable "llm_hostname" {
  description = "Name of the university's LLM server (the containers get it through extra_hosts)"
  type        = string
  default     = "coretex.local.univ-savoie.fr"
}

variable "llm_port" {
  type    = number
  default = 8080
}

variable "agent_env" {
  description = "Non-secret settings of the agent (Línea A's .env.agent.example). Secrets come from Parameter Store"
  type        = map(string)
  default = {
    ACLOPI_LLM_PROVIDER         = "openai_compat"
    ACLOPI_LLM_MODEL            = "strata"
    ACLOPI_LLM_REASONING_EFFORT = "none"
    ACLOPI_LLM_TIMEOUT_S        = "30"
    ACLOPI_LLM_MAX_TOKENS       = "200"
    ACLOPI_LLM_JSON_MODE        = "auto"
    ACLOPI_SEQUENCE_TIMEOUT_S   = "90"
    ACLOPI_SEQUENCE_REASONING   = "medium"
    LLM_MAX_PARALLEL            = "2"
    ACLOPI_U_WIDE               = "100"
    ACLOPI_U_NARROW             = "50"
    ACLOPI_WHATIF_P95_S         = "5.5"
    ACLOPI_LLM2_LATENCY_S       = "3"
    ACLOPI_FAST_DEADLINE_S      = "60"
  }
}

variable "platform_env" {
  description = "Extra settings of the platform API (aclopi/api/settings.py)"
  type        = map(string)
  default = {
    ACLOPI_LOG_LEVEL = "INFO"
  }
}

# ----- monitoring and cost -----

variable "alert_email" {
  description = "Receives alarms and budget alerts (AWS sends a confirmation e-mail first)"
  type        = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 100
}

# ----- GitHub Actions -----

variable "github_repository" {
  description = "owner/repo allowed to deploy (case-sensitive)"
  type        = string
  default     = "ACLOPI-SYMME/Netlogo"
}

variable "github_deploy_branch" {
  type    = string
  default = "main"
}

variable "create_github_oidc_provider" {
  description = "false if the account already has the token.actions.githubusercontent.com provider"
  type        = bool
  default     = true
}
