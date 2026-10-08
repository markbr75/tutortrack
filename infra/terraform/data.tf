# --- PostgreSQL (RDS) -----------------------------------------------------------------------------

resource "random_password" "db" {
  length  = 40
  special = false
}

# Application (RLS-restricted) and platform (BYPASSRLS) roles, created by the migrate task
# with `manage.py ensure_db_roles` (FR-02-4). The master user owns the tables.
resource "random_password" "db_app" {
  length  = 40
  special = false
}

resource "random_password" "db_platform" {
  length  = 40
  special = false
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

resource "aws_db_instance" "postgres" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 50
  max_allocated_storage = 500
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "tutortrack"
  username = "tutortrack_owner" # owns tables; the app connects as a non-owner role (E02 RLS)
  password = random_password.db.result

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.data.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  multi_az               = var.db_multi_az

  backup_retention_period      = 35 # point-in-time recovery window (E30 FR-30-4)
  copy_tags_to_snapshot        = true
  deletion_protection          = var.environment == "production"
  skip_final_snapshot          = var.environment != "production"
  final_snapshot_identifier    = "${local.name}-final"
  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
}

# --- Redis (ElastiCache) --------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "redis" {
  name       = local.name
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = local.name
  description                = "TutorTrack cache, Celery broker and locks"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.environment == "production" ? 2 : 1
  automatic_failover_enabled = var.environment == "production"
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# --- Object storage (uploads) ---------------------------------------------------------------------

resource "aws_s3_bucket" "uploads" {
  bucket = "${local.name}-uploads"
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_cors_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  cors_rule {
    allowed_methods = ["GET", "PUT"]
    allowed_origins = ["https://*.${var.app_domain}"] # tenant custom domains added in E24
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# --- Secrets --------------------------------------------------------------------------------------

resource "random_password" "django_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name = "${local.name}/app"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DJANGO_SECRET_KEY = random_password.django_secret.result
    DATABASE_URL = format(
      "postgres://tutortrack_app:%s@%s/tutortrack?sslmode=require",
      random_password.db_app.result,
      aws_db_instance.postgres.endpoint,
    )
    DATABASE_OWNER_URL = format(
      "postgres://%s:%s@%s/tutortrack?sslmode=require",
      aws_db_instance.postgres.username,
      random_password.db.result,
      aws_db_instance.postgres.endpoint,
    )
    DATABASE_PLATFORM_URL = format(
      "postgres://tutortrack_platform:%s@%s/tutortrack?sslmode=require",
      random_password.db_platform.result,
      aws_db_instance.postgres.endpoint,
    )
    REDIS_URL         = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
    CELERY_BROKER_URL = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/1"
    # Set the real Cloudflare Turnstile secret in Secrets Manager; prod refuses to start empty.
    TURNSTILE_SECRET_KEY = ""
  })

  lifecycle {
    ignore_changes = [secret_string] # rotated/extended outside Terraform (Sentry DSN, providers)
  }
}
