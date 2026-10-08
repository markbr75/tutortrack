output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "cloudfront_domain_name" {
  description = "Point *.<app_domain> (CNAME/alias) here."
  value       = aws_cloudfront_distribution.app.domain_name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.bucket
}

output "app_secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}
