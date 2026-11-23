# IAM: the instance role (minimum permissions) and the GitHub Actions deploy role (OIDC, no stored keys).

locals {
  param_prefix = "/${var.project}"
  param_arn    = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.param_prefix}/*"
}

# ----- instance role -----

resource "aws_iam_role" "instance" {
  name = "${var.project}-instance"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

# SSM agent (Session Manager, Run Command for deployments) and CloudWatch Agent (metrics, logs).
resource "aws_iam_role_policy_attachment" "instance_managed" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])
  role       = aws_iam_role.instance.name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "instance" {
  name = "${var.project}-instance"
  role = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Secrets"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = [local.param_arn]
      },
      {
        Sid       = "DecryptSecureStrings"
        Effect    = "Allow"
        Action    = ["kms:Decrypt"]
        Resource  = ["*"]
        Condition = { StringEquals = { "kms:ViaService" = "ssm.${var.region}.amazonaws.com" } }
      },
      {
        Sid      = "History"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchWriteItem", "dynamodb:BatchGetItem", "dynamodb:DescribeTable"]
        Resource = [for t in aws_dynamodb_table.app : t.arn]
      },
      {
        Sid      = "Artifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        # The user data re-attaches the Elastic IP when the ASG replaces the instance.
        Sid      = "ElasticIp"
        Effect   = "Allow"
        Action   = ["ec2:AssociateAddress"]
        Resource = ["arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:elastic-ip/${aws_eip.platform.allocation_id}", "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*", "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:network-interface/*"]
      },
      {
        Sid      = "Describe"
        Effect   = "Allow"
        Action   = ["ec2:DescribeAddresses", "ec2:DescribeInstances"]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.project}-instance"
  role = aws_iam_role.instance.name
}

# ----- GitHub Actions deploy role -----

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f2df264fcd"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_role" "deploy" {
  name = "${var.project}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # Only workflows running on the deploy branch of this repository.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:ref:refs/heads/${var.github_deploy_branch}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  name = "${var.project}-github-deploy"
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "EcrLogin", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = ["*"] },
      {
        Sid      = "EcrPush"
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"]
        Resource = [for r in aws_ecr_repository.app : r.arn]
      },
      {
        Sid      = "ImageTag"
        Effect   = "Allow"
        Action   = ["ssm:PutParameter", "ssm:GetParameter"]
        Resource = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.param_prefix}/deploy/*"]
      },
      {
        Sid      = "RunDeployOnInstance"
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = ["arn:aws:ssm:${var.region}::document/AWS-RunShellScript"]
      },
      {
        Sid       = "RunDeployOnTaggedInstance"
        Effect    = "Allow"
        Action    = ["ssm:SendCommand"]
        Resource  = ["arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*"]
        Condition = { StringEquals = { "ssm:resourceTag/Role" = "${var.project}-platform" } }
      },
      {
        Sid      = "FollowDeploy"
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ec2:DescribeInstances"]
        Resource = ["*"]
      },
    ]
  })
}
