output "platform_url" {
  description = "The platform, for the users"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "ecr_platform" {
  value = aws_ecr_repository.app["platform"].repository_url
}

output "ecr_agent" {
  value = aws_ecr_repository.app["agent"].repository_url
}

output "github_deploy_role_arn" {
  description = "Repository variable AWS_DEPLOY_ROLE_ARN (README, step 7)"
  value       = aws_iam_role.deploy.arn
}

output "elastic_ip" {
  description = "Fixed public IP of the instance (in case the university asks to allow it in the VPN)"
  value       = aws_eip.platform.public_ip
}

output "autoscaling_group" {
  value = aws_autoscaling_group.platform.name
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "dynamodb_tables" {
  value = [for t in aws_dynamodb_table.app : t.name]
}

output "ami" {
  description = "Ubuntu image the instance uses"
  value       = "${data.aws_ami.ubuntu.name} (${data.aws_ami.ubuntu.id})"
}
