resource "aws_ecr_repository" "backend" {
  name                 = "tutortrack-backend"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

# --- IAM ------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.app.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_s3" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.uploads.arn, "${aws_s3_bucket.uploads.arn}/*"]
    }]
  })
}

# --- Task definitions -----------------------------------------------------------------------------

locals {
  secret_keys = ["DJANGO_SECRET_KEY", "DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL"]

  container_base = {
    image     = var.backend_image
    essential = true
    environment = [
      { name = "DJANGO_SETTINGS_MODULE", value = "config.settings.prod" },
      { name = "DJANGO_ALLOWED_HOSTS", value = ".${var.app_domain}" },
      { name = "TENANT_BASE_DOMAIN", value = var.app_domain },
      { name = "AWS_STORAGE_BUCKET_NAME", value = aws_s3_bucket.uploads.bucket },
      { name = "AWS_S3_REGION_NAME", value = var.region },
      { name = "CLAMAV_ENABLED", value = "true" },
      { name = "LOG_JSON", value = "true" },
    ]
    secrets = [for key in local.secret_keys : {
      name      = key
      valueFrom = "${aws_secretsmanager_secret.app.arn}:${key}::"
    }]
  }

  processes = {
    web     = { command = null, cpu = 512, memory = 1024, port = true }
    worker  = { command = ["celery", "-A", "config", "worker", "-l", "INFO", "-Q", "default,outbox,notifications,billing,integrations,imports,reports"], cpu = 512, memory = 1024, port = false }
    beat    = { command = ["celery", "-A", "config", "beat", "-l", "INFO"], cpu = 256, memory = 512, port = false }
    migrate = { command = ["python", "manage.py", "migrate", "--noinput"], cpu = 256, memory = 512, port = false }
  }
}

resource "aws_ecs_task_definition" "process" {
  for_each = local.processes

  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([merge(local.container_base, {
    name         = each.key
    command      = each.value.command
    portMappings = each.value.port ? [{ containerPort = 8000, protocol = "tcp" }] : []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  })])

  lifecycle {
    ignore_changes = [container_definitions] # CI registers new revisions with each image
  }
}

# --- Load balancer --------------------------------------------------------------------------------

resource "aws_lb" "main" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = module.vpc.public_subnets
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name}-web"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = module.vpc.vpc_id

  health_check {
    path    = "/healthz"
    matcher = "200"
  }
  deregistration_delay = 30
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# --- Services -------------------------------------------------------------------------------------

locals {
  services = {
    web    = var.web_desired_count
    worker = var.worker_desired_count
    beat   = 1 # exactly one scheduler
  }
}

resource "aws_ecs_service" "process" {
  for_each = local.services

  name            = "tutortrack-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.process[each.key].arn
  desired_count   = each.value
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = module.vpc.private_subnets
    security_groups = [aws_security_group.app.id]
  }

  dynamic "load_balancer" {
    for_each = each.key == "web" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.web.arn
      container_name   = "web"
      container_port   = 8000
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition] # managed by the deploy workflow
  }
}

# Network settings the deploy workflow uses to run the one-off migrate task.
resource "aws_ssm_parameter" "ecs_network" {
  name = "/tutortrack/${var.environment}/ecs/network"
  type = "String"
  value = format(
    "awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=DISABLED}",
    join(",", module.vpc.private_subnets),
    aws_security_group.app.id,
  )
}
