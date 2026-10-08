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
