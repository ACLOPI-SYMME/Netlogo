# One EC2 instance in an ASG of 1 (self-healing), warm pool (stopped off-hours), schedule and Elastic IP.

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

# Fixed origin of CloudFront. Stays associated while the instance is stopped in the warm pool;
# the boot script re-associates it when the ASG creates a new instance.
resource "aws_eip" "platform" {
  domain = "vpc"
  tags   = { Name = "${var.project}-platform" }
}

locals {
  ecr_registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"

  user_data = templatefile("${path.module}/files/user_data.sh.tftpl", {
    region         = var.region
    project        = var.project
    param_prefix   = local.param_prefix
    eip_allocation = aws_eip.platform.allocation_id
    ecr_registry   = local.ecr_registry
    platform_repo  = aws_ecr_repository.app["platform"].repository_url
    agent_repo     = aws_ecr_repository.app["agent"].repository_url
    table_prefix   = local.table_prefix
    llm_hostname   = var.llm_hostname
    llm_port       = var.llm_port
    image_tag      = var.image_tag
    log_group_app  = aws_cloudwatch_log_group.app["platform"].name
    log_group_agt  = aws_cloudwatch_log_group.app["agent"].name
    log_group_sys  = aws_cloudwatch_log_group.app["system"].name
    agent_env      = join("\n", [for k, v in var.agent_env : "${k}=${v}"])
    platform_env   = join("\n", [for k, v in var.platform_env : "${k}=${v}"])
    compose_file   = file("${path.module}/files/docker-compose.aws.yml")
    vpn_script     = file("${path.module}/files/vpn.sh")
    start_script   = file("${path.module}/files/start.sh")
    health_script  = file("${path.module}/files/health.sh")
  })
}

resource "aws_launch_template" "platform" {
  name_prefix   = "${var.project}-platform-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  user_data     = base64gzip(local.user_data) # cloud-init accepts gzip; keeps it far below the 16 KB limit

  iam_instance_profile {
    arn = aws_iam_instance_profile.instance.arn
  }

  network_interfaces {
    associate_public_ip_address = true # needed to reach the AWS API before the Elastic IP is attached
    security_groups             = [aws_security_group.platform.id]
  }

  block_device_mappings {
    device_name = data.aws_ami.ubuntu.root_device_name
    ebs {
      volume_size           = var.root_volume_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  metadata_options {
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 2          # containers (boto3 in the API) reach the instance role
  }

  monitoring {
    enabled = false
  }

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project}-platform", Role = "${var.project}-platform" }
  }
  tag_specifications {
    resource_type = "volume"
    tags          = { Name = "${var.project}-platform" }
  }
}

resource "aws_autoscaling_group" "platform" {
  name                      = "${var.project}-platform"
  min_size                  = 0
  max_size                  = 1
  desired_capacity          = var.initial_capacity
  vpc_zone_identifier       = aws_subnet.public[*].id
  health_check_type         = "EC2" # no load balancer (decided 9 Nov); /health/ready is watched by an alarm
  health_check_grace_period = 300
  capacity_rebalance        = false

  launch_template {
    id      = aws_launch_template.platform.id
    version = aws_launch_template.platform.latest_version
  }

  # Off-hours the instance goes back STOPPED to the warm pool and the same one starts the next morning
  # (image and VPN already on its disk). Decided 28 Oct (Línea B context, section 0).
  warm_pool {
    pool_state                  = "Stopped"
    min_size                    = 0
    max_group_prepared_capacity = 1
    instance_reuse_policy {
      reuse_on_scale_in = true
    }
  }

  tag {
    key                 = "Role"
    value               = "${var.project}-platform"
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity] # the schedule moves it
  }
}

resource "aws_autoscaling_schedule" "start" {
  scheduled_action_name  = "${var.project}-start"
  autoscaling_group_name = aws_autoscaling_group.platform.name
  recurrence             = var.schedule_start
  time_zone              = var.schedule_timezone
  min_size               = 0
  max_size               = 1
  desired_capacity       = 1
}

resource "aws_autoscaling_schedule" "stop" {
  scheduled_action_name  = "${var.project}-stop"
  autoscaling_group_name = aws_autoscaling_group.platform.name
  recurrence             = var.schedule_stop
  time_zone              = var.schedule_timezone
  min_size               = 0
  max_size               = 1
  desired_capacity       = 0
}
