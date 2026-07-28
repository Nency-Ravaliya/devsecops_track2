# FIXED: CLD-002 — RDS instance is public, unencrypted, and has no backups
#
# This file shows the corrected terraform for the aws_db_instance resource
# that was flagged as Critical in Module 1 (findings-register.md).
#
# BEFORE (vulnerable):
#   publicly_accessible    = true
#   storage_encrypted      = false
#   backup_retention_period = 0
#   vpc_security_group_ids = [aws_security_group.web-node.id] (allows 0.0.0.0/0 on 22)
#
# AFTER (hardened):
#   - Private subnet only, no public IP
#   - Encryption at rest with customer-managed KMS key
#   - 7-day backup retention with point-in-time recovery
#   - TLS enforced via parameter group
#   - Security group restricts access to application tier only

# --- KMS key for RDS encryption ---
resource "aws_kms_key" "rds_key" {
  description             = "Customer-managed key for RDS encryption"
  enable_key_rotation     = true  # CLD-022 fix: enable automatic rotation
  deletion_window_in_days = 30

  tags = {
    Name        = "rds-encryption-key"
    Environment = "production"
    Workload    = "db-app"
  }
}

resource "aws_kms_alias" "rds_key" {
  name          = "alias/rds-db-app"
  target_key_id = aws_kms_key.rds_key.key_id
}

# --- Private security group for the database ---
resource "aws_security_group" "db_private" {
  name        = "db-app-private-sg"
  description = "Allow MySQL access from application tier only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name        = "db-app-private-sg"
    Environment = "production"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "db_ingress_from_app" {
  type                     = "ingress"
  from_port                = 3306
  to_port                  = 3306
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.app_tier.id
  security_group_id        = aws_security_group.db_private.id
  description              = "MySQL from application tier only"
}

resource "aws_security_group_rule" "db_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.db_private.id
  description       = "Allow outbound (required for RDS maintenance)"
}

# --- TLS-enforced parameter group ---
resource "aws_db_parameter_group" "secure_mysql" {
  family = "mysql8.0"
  name   = "db-app-secure-params"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "require_secure_transport"
    value = "ON"
  }

  tags = {
    Name = "db-app-secure-params"
  }
}

# --- Subnet group for private subnets only ---
resource "aws_db_subnet_group" "private" {
  name        = "db-app-private-subnet-group"
  description = "Private subnet group for RDS"
  subnet_ids  = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "db-app-private-subnet-group"
  }
}

# --- The corrected RDS instance ---
resource "aws_db_instance" "default" {
  identifier = "db-app"

  engine         = "mysql"
  engine_version = "8.0"
  instance_class = "db.t3.medium"

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"

  db_name  = var.dbname
  username = var.username
  password = var.password  # In production, source from Secrets Manager, not a variable

  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.db_private.id]
  parameter_group_name   = aws_db_parameter_group.secure_mysql.name

  # --- CLD-002 fixes ---
  publicly_accessible    = false          # FIX: was true — no public access
  storage_encrypted      = true           # FIX: was false — encryption at rest enabled
  kms_key_id             = aws_kms_key.rds_key.arn
  backup_retention_period = 7             # FIX: was 0 — 7-day backup retention
  preferred_backup_window = "03:00-04:00"
  backup_window           = "02:00-03:00"

  # --- Additional hardening ---
  multi_az               = true
  deletion_protection    = true
  copy_tags_to_snapshot  = true
  monitoring_interval    = 60
  monitoring_role_arn    = aws_iam_role.rds_monitoring.arn
  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.rds_key.arn
  enabled_cloudwatch_logs_exports = ["error", "general", "slowquery"]

  tags = {
    Name           = "db-app"
    Environment    = "production"
    Classification = "sensitive"
    Backup         = "required"
  }
}

# --- Secrets Manager for the database password (best practice, replaces var.password) ---
# Uncomment and migrate to this approach to fully address CLD-007:
#
# resource "aws_secretsmanager_secret" "db_password" {
#   name = "db-app/database-password"
# }
#
# resource "aws_secretsmanager_secret_version" "db_password" {
#   secret_id = aws_secretsmanager_secret.db_password.id
#   secret_string = random_password.db_password.result
# }
#
# resource "random_password" "db_password" {
#   length           = 32
#   special          = true
#   override_special = "!#$%&*()-_=+[]{}|:?"
# }
#
# Then reference: password = aws_secretsmanager_secret_version.db_password.secret_string
