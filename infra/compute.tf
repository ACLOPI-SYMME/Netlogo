# One EC2 instance, started and stopped on a schedule (EventBridge Scheduler), with a fixed Elastic IP.
# Decided 23 Nov: a plain instance instead of an ASG of 1 + warm pool. Stopping keeps the disk (image and VPN
# already installed), so the next start takes ~2-3 min; AWS automatic recovery moves it to another host on a
# hardware failure. A broken instance is replaced by hand: terraform apply -replace=aws_instance.platform

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = [var.ami_name_filter]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

locals {
  ecr_registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"

  user_data = templatefile("${path.module}/files/user_data.sh.tftpl", {
    region        = var.region
    project       = var.project
    param_prefix  = local.param_prefix
    ecr_registry  = local.ecr_registry
    platform_repo = aws_ecr_repository.app["platform"].repository_url
    agent_repo    = aws_ecr_repository.app["agent"].repository_url
    table_prefix  = local.table_prefix
    llm_hostname  = var.llm_hostname
    llm_port      = var.llm_port
    image_tag     = var.image_tag
    log_group_app = aws_cloudwatch_log_group.app["platform"].name
    log_group_agt = aws_cloudwatch_log_group.app["agent"].name
    log_group_sys = aws_cloudwatch_log_group.app["system"].name
    agent_env     = join("\n", [for k, v in var.agent_env : "${k}=${v}"])
    platform_env  = join("\n", [for k, v in var.platform_env : "${k}=${v}"])
    compose_file  = file("${path.module}/files/docker-compose.aws.yml")
    vpn_script    = file("${path.module}/files/vpn.sh")
    start_script  = file("${path.module}/files/start.sh")
    health_script = file("${path.module}/files/health.sh")
  })
}

resource "aws_instance" "platform" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.platform.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true                        # replaced by the Elastic IP once it is attached
  user_data_base64            = base64gzip(local.user_data) # cloud-init accepts gzip; far below the 16 KB limit
  monitoring                  = false

  root_block_device {
    volume_size           = var.root_volume_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
    tags                  = { Name = "${var.project}-platform" }
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 2          # containers (boto3 in the API) reach the instance role
  }

  maintenance_options {
    auto_recovery = "default" # move to healthy hardware if the host fails
  }

  tags = { Name = "${var.project}-platform", Role = "${var.project}-platform" }

  lifecycle {
    # The user data runs only on the first boot, and a newer Ubuntu AMI must not replace a working instance.
    # To apply either one: terraform apply -replace=aws_instance.platform
    ignore_changes = [ami, user_data, user_data_base64]
  }
}

# Fixed origin of CloudFront; stays attached while the instance is stopped.
resource "aws_eip" "platform" {
  domain   = "vpc"
  instance = aws_instance.platform.id
  tags     = { Name = "${var.project}-platform" }
}

# ----- schedule: EventBridge Scheduler calls EC2 StartInstances / StopInstances -----

resource "aws_iam_role" "scheduler" {
  name = "${var.project}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${var.project}-scheduler"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "StartStop", Effect = "Allow", Action = ["ec2:StartInstances", "ec2:StopInstances"], Resource = [aws_instance.platform.arn] },
      {
        # Starting an instance with an encrypted disk uses the EBS key.
        Sid       = "EncryptedDisk"
        Effect    = "Allow"
        Action    = ["kms:CreateGrant", "kms:Decrypt", "kms:GenerateDataKeyWithoutPlaintext", "kms:ReEncrypt*"]
        Resource  = ["*"]
        Condition = { StringEquals = { "kms:ViaService" = "ec2.${var.region}.amazonaws.com" } }
      },
    ]
  })
}

resource "aws_scheduler_schedule" "platform" {
  for_each = {
    start = { cron = var.schedule_start, action = "startInstances" }
    stop  = { cron = var.schedule_stop, action = "stopInstances" }
  }
  name                         = "${var.project}-${each.key}"
  schedule_expression          = each.value.cron
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:${each.value.action}"
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ InstanceIds = [aws_instance.platform.id] })
  }
}
