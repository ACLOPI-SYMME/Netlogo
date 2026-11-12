# ECR (images), DynamoDB (history) and S3 (offline page and artifacts).

# ----- ECR -----

resource "aws_ecr_repository" "app" {
  for_each             = toset(["platform", "agent"])
  name                 = "${var.project}-${each.key}"
  image_tag_mutability = "MUTABLE" # "latest" is overwritten on each deployment
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# ----- DynamoDB: same tables and keys as DynamoResultsStore.create_tables (aclopi/api/results.py) -----

locals {
  tables = {
    runs         = { hash = "run_id", range = null }
    decisions    = { hash = "run_id", range = "seq" }
    product_sets = { hash = "id", range = null }
  }
  table_prefix = "${var.project}_"
}

resource "aws_dynamodb_table" "app" {
  for_each     = local.tables
  name         = "${local.table_prefix}${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash
  range_key    = each.value.range

  attribute {
    name = each.value.hash
    type = "S"
  }

  dynamic "attribute" {
    for_each = each.value.range == null ? [] : [each.value.range]
    content {
      name = attribute.value
      type = "N"
    }
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ----- S3 -----

# Only the "platform off" page, read by CloudFront (OAC) when the instance does not answer.
resource "aws_s3_bucket" "offline" {
  bucket = "${var.project}-offline-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "offline" {
  bucket                  = aws_s3_bucket.offline.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "offline_page" {
  bucket        = aws_s3_bucket.offline.id
  key           = "offline/index.html"
  content       = templatefile("${path.module}/files/offline.html.tftpl", { start = var.schedule_start, stop = var.schedule_stop, tz = var.schedule_timezone })
  content_type  = "text/html; charset=utf-8"
  cache_control = "max-age=10"
}

resource "aws_s3_bucket_policy" "offline" {
  bucket = aws_s3_bucket.offline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "CloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.offline.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.main.arn } }
    }]
  })
}

# Run exports, experiment results, datasets, what-if diagnostics.
resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.project}-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-diagnostics"
    status = "Enabled"
    filter {
      prefix = "diagnostics/"
    }
    expiration {
      days = 30
    }
  }
}
