# CloudFront: the only way in (decided 9 Nov). HTTPS on *.cloudfront.net without our own domain.
# Everything (page /ui, API, WebSocket /ws/...) goes to the instance, uncached; the routes do not change.
# The page is a single live.html served by the API, so there is no cached static path.
# When the instance does not answer (502/504: off-hours, starting, failure) the "offline" page comes from S3.

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# Shared secret: CloudFront adds it and the API demands it from CloudFront requests (aclopi/api/origin.py).
# Created by scripts/aws/put-secrets.sh BEFORE the first apply.
data "aws_ssm_parameter" "origin_verify" {
  name            = "${local.param_prefix}/app/origin_verify"
  with_decryption = true
}

resource "aws_cloudfront_origin_access_control" "offline" {
  name                              = "${var.project}-offline"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  comment             = "${var.project} simulation platform"
  price_class         = "PriceClass_100" # Europe and North America: the cheapest
  http_version        = "http2"
  default_root_object = "ui" # "/" opens the page (GET /ui)

  # The instance, through its Elastic IP's public DNS name (CloudFront needs a name, not an IP).
  origin {
    origin_id   = "platform"
    domain_name = aws_eip.platform.public_dns

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only" # no valid certificate is possible for that name
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 5
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = data.aws_ssm_parameter.origin_verify.value
    }
  }

  origin {
    origin_id                = "offline"
    domain_name              = aws_s3_bucket.offline.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.offline.id
  }

  default_cache_behavior {
    target_origin_id         = "platform"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true
  }

  ordered_cache_behavior {
    path_pattern           = "/offline/*"
    target_origin_id       = "offline"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  # Origin unreachable -> offline page. The API's 503 ("platform starting") is left alone: the page shows it.
  dynamic "custom_error_response" {
    for_each = [502, 504]
    content {
      error_code            = custom_error_response.value
      response_code         = 503
      response_page_path    = "/offline/index.html"
      error_caching_min_ttl = 10
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
