variable "environment" {
  description = "staging or production"
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  description = "Primary region. Data residency (E29): one stack per region (eu-west-2 = UK)."
  type        = string
  default     = "eu-west-2"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "app_domain" {
  description = "Base domain, e.g. tutortrack.app (tenants get <slug>.tutortrack.app)."
  type        = string
}

variable "acm_certificate_arn" {
  description = "Regional ACM certificate covering app_domain and *.app_domain (for the ALB)."
  type        = string
}

variable "cloudfront_certificate_arn" {
  description = "us-east-1 ACM certificate for the static frontend distribution."
  type        = string
}

variable "backend_image" {
  description = "Initial backend image; CI replaces it on each deploy."
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "web_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "temporal_address" {
  description = "Temporal Cloud gRPC endpoint, e.g. tutortrack-staging.abcde.tmprl.cloud:7233 (E32)"
  type        = string
  default     = ""
}

variable "temporal_namespace" {
  description = "Temporal Cloud namespace for this environment (one per environment, not per tenant)"
  type        = string
  default     = ""
}

variable "temporal_worker_desired_count" {
  description = "Temporal worker tasks"
  type        = number
  default     = 1
}

# --- Operations (E30) -----------------------------------------------------------------------------

variable "alert_email" {
  description = "Email subscribed to the alarm topic (empty = none)"
  type        = string
  default     = ""
}

variable "pagerduty_endpoint" {
  description = "PagerDuty (or Opsgenie) CloudWatch integration URL for paging alarms (empty = none)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "platform_ip_allowlist" {
  description = "CIDRs allowed to use the platform console (office VPN)"
  type        = list(string)
  default     = []
}

variable "status_page_url" {
  description = "Public status page shown in the apps"
  type        = string
  default     = ""
}

variable "backup_copy_vault_arn" {
  description = "AWS Backup vault in the separate backup account to copy daily snapshots to (empty = no copy)"
  type        = string
  default     = ""
}
