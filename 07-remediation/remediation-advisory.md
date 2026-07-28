# Module 7 — Remediation Advisory Pack

## Purpose

This module provides delivery-facing remediation guidance for the three most critical findings from the Module 1 findings register. The guidance is written for engineers who may not have a security background — plain language, no unexplained jargon, step-by-step instructions, and clear evidence of completion.

## Finding CLD-002 — AWS RDS MySQL instance is public, unencrypted, and has no backups

### Risk explanation (plain language)

Your database can be reached by anyone on the internet (`publicly_accessible = true`). The data it stores is not encrypted on disk (`storage_encrypted = false`), so if someone copies the storage or takes a snapshot, they can read everything in plain text. There are no automated backups (`backup_retention_period = 0`), meaning if data is deleted or corrupted, it's gone permanently.

This is the equivalent of putting your filing cabinet on the street with the lock removed and no photocopies in a safe.

### Remediation steps

**Step 1: Enable backups (do this first — it's the fastest win and protects against accidental data loss during the rest of the fix)**

In `reference-target/terraform/aws/db-app.tf`, change:

```hcl
# BEFORE (CLD-002)
resource "aws_db_instance" "default" {
  ...
  backup_retention_period = 0
  ...
}

# AFTER
resource "aws_db_instance" "default" {
  ...
  backup_retention_period = 7
  preferred_backup_window = "03:00-04:00"
  ...
}
```

**Step 2: Disable public accessibility and move to a private subnet**

```hcl
# AFTER
resource "aws_db_instance" "default" {
  ...
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.private.name
  vpc_security_group_ids = [aws_security_group.db_private.id]
  ...
}
```

Create a private-only security group that only allows ingress from the application subnet on port 3306:

```hcl
resource "aws_security_group" "db_private" {
  name        = "db-private-sg"
  description = "Allow MySQL from application subnet only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "MySQL from app tier"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app_tier.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

**Step 3: Enable encryption at rest**

```hcl
resource "aws_db_instance" "default" {
  ...
  storage_encrypted = true
  kms_key_id        = aws_kms_key.rds_key.arn
  ...
}

resource "aws_kms_key" "rds_key" {
  description             = "RDS encryption key for workload"
  enable_key_rotation     = true
}
```

> **Important:** `storage_encrypted` can only be set at creation time for most RDS engines. If the instance already exists, you must create a snapshot, restore from the snapshot with encryption enabled, and update DNS to point to the new instance. Plan a maintenance window.

**Step 4: Force TLS for all connections**

```hcl
resource "aws_db_parameter_group" "secure" {
  family = "mysql8.0"
  name   = "secure-params"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}
```

### Evidence of completion

| Check | How to verify | Evidence artifact |
|---|---|---|
| Database no longer publicly accessible | `aws rds describe-db-instances --db-instance-identifier <id> --query 'DBInstances[0].PubliclyAccessible'` returns `false` | CLI output screenshot or Terraform plan showing `publicly_accessible = false` |
| Encryption enabled | `aws rds describe-db-instances --query 'DBInstances[0].StorageEncrypted'` returns `true` | CLI output |
| Backups enabled | `aws rds describe-db-instances --query 'DBInstances[0].BackupRetentionPeriod'` returns `>= 7` | CLI output |
| Security group restricts access | Review SG rules: only application subnet CIDR on port 3306 | SG rule list |
| TLS enforced | Connect to database and verify `SHOW STATUS LIKE 'Ssl_cipher'` returns a cipher | MySQL client output |
| KMS key rotation | `aws kms get-key-rotation-status --key-id <arn>` returns `KeyRotationEnabled: true` | CLI output |

---

## Finding CLD-003 — AWS IAM user policy grants wildcard service permissions on all resources

### Risk explanation (plain language)

The CI service account has permissions that let it do anything to EC2, S3, Lambda, and CloudWatch across the entire AWS account. If someone steals the CI credentials (which are static access keys committed in `CLD-004`), they can read every S3 bucket, delete every Lambda function, stop every EC2 instance, and modify every CloudWatch alarm. This is the equivalent of giving the office cleaner the master key to every room, including the safe.

### Remediation steps

**Step 1: Replace the wildcard user policy with workload-scoped roles**

Delete the existing `aws_iam_user_policy.userpolicy` in `reference-target/terraform/aws/iam.tf`:

```hcl
# REMOVE (CLD-003)
resource "aws_iam_user_policy" "userpolicy" {
  name = "userpolicy"
  user = aws_iam_user.ci_user.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:*", "s3:*", "lambda:*", "cloudwatch:*"]
      Resource = "*"
    }]
  })
}
```

**Step 2: Create the replacement roles as defined in Module 3**

The complete replacement policy is documented in `../03-identity-governance/cross-cloud-iam-design.md` under "Specific redesign of the wildcard CI service account." Create:

1. `ci-plan-readonly` — read-only for `terraform plan`, scoped by `sts:AssumeRoleWithWebIdentity` trust to the GitLab OIDC provider.
2. `ci-deploy-workload` — write permissions scoped to workload resources by tag condition.
3. `ci-deploy-shared-infra` — broader permissions for shared infrastructure, with manual approval gate.

The core principle: **every action is explicit, every resource is scoped by ARN or tag, and no action is on `*`.**

**Step 3: Remove long-lived access keys**

```hcl
# REMOVE
resource "aws_iam_access_key" "user_key" {
  user = aws_iam_user.ci_user.name
}
```

Replace with OIDC federation trust policy (see Module 3 for the exact trust policy document).

### Evidence of completion

| Check | How to verify | Evidence artifact |
|---|---|---|
| Wildcard policy deleted | `aws iam list-user-policies --user-name <user>` returns empty list | CLI output |
| Scoped roles exist with correct trust | `aws iam get-role --role-name ci-plan-readonly` shows OIDC trust | CLI output |
| No static access keys exist | `aws iam list-access-keys --user-name <user>` returns empty (or user is deleted) | CLI output |
| Pipeline works with OIDC | GitLab pipeline runs `terraform plan` successfully using OIDC role assumption | Pipeline log |
| OPA check passes | Checkov/Conftest denies any IAM wildcard in future PRs | Pipeline checkov-scan job output |

---

## Finding CLD-025 — Azure SQL/MSSQL admin passwords are hardcoded across multiple servers

### Risk explanation (plain language)

Seven SQL servers and one legacy SQL Server all have the same admin password (`AdminPassword123!` or `Aa12345678`) committed in the Terraform code. Anyone with read access to the repository — or who can access the Git history — has the password for every database. Because the password is the same across servers, compromising one compromises all of them.

### Remediation steps

**Step 1: Rotate every password immediately**

Before changing any Terraform, generate a new unique password for each server and apply it manually through the Azure portal. This stops the old committed password from being valid.

**Step 2: Move credentials to Azure Key Vault**

The repo already provisions a Key Vault in `reference-target/terraform/azure/key_vault.tf`. Use it:

```hcl
resource "azurerm_key_vault_secret" "mssql_admin" {
  for_each     = toset(["mssql1", "mssql2", "mssql3", "mssql4", "mssql5", "mssql6", "mssql7"])
  name         = "${each.key}-admin-password"
  value        = random_password.mssql[each.key].result
  key_vault_id = azurerm_key_vault.main.id
}

resource "random_password" "mssql" {
  for_each = toset(["mssql1", "mssql2", "mssql3", "mssql4", "mssql5", "mssql6", "mssql7"])
  length   = 32
  special  = true
}
```

**Step 3: Reference Key Vault secrets in MSSQL server resources**

```hcl
# BEFORE (CLD-025)
resource "azurerm_mssql_server" "mssql1" {
  ...
  administrator_login_password = "AdminPassword123!"
  ...
}

# AFTER
resource "azurerm_mssql_server" "mssql1" {
  ...
  administrator_login_password = azurerm_key_vault_secret.mssql["mssql1"].value
  ...
}
```

**Step 4: Re-enable SQL injection and data exfiltration alerts (`CLD-024`)**

```hcl
# BEFORE
resource "azurerm_mssql_server_security_alert_policy" "alertpolicy1" {
  ...
  disabled_alerts = ["Sql_Injection", "Data_Exfiltration"]
  ...
}

# AFTER
resource "azurerm_mssql_server_security_alert_policy" "alertpolicy1" {
  ...
  disabled_alerts = []
  email_account_admins = true
  email_addresses       = ["security@example.gov.uk"]
  ...
}
```

### Evidence of completion

| Check | How to verify | Evidence artifact |
|---|---|---|
| No hardcoded passwords in code | `grep -r "AdminPassword123\|Aa12345678" terraform/azure/` returns empty | Grep output |
| Key Vault contains unique secrets per server | `az keyvault secret list --vault-name <kv>` shows 7 unique secrets | CLI output |
| Each MSSQL server references Key Vault | Terraform plan shows `administrator_login_password = (sensitive value)` from Key Vault | Plan output |
| Alerts re-enabled | `az sql server ssir-policy list` shows empty `disabledAlerts` | CLI output |
| Passwords are unique | Compare secret values — each is a different 32-character random string | (Don't screenshot actual values — just confirm they differ) |

---

## Corrected Terraform files

Actual corrected HCL files are in `fixed-terraform/`:

- `fixed-terraform/aws-db-app.tf` — corrected `CLD-002`: RDS instance with encryption, private subnet, backups, and TLS.
- `fixed-terraform/aws-iam-ci.tf` — corrected `CLD-003`: scoped IAM roles replacing the wildcard policy.
- `fixed-terraform/azure-mssql.tf` — corrected `CLD-025`: Key Vault secrets replacing hardcoded passwords.

## Cross-references

- Findings register (all three findings): `../01-findings/findings-register.md`
- Identity governance (CLD-003 replacement design): `../03-identity-governance/cross-cloud-iam-design.md`
- Pipeline (prevention of future regressions): `../02-pipeline-supply-chain/pipeline-design.md`
- Compensating controls (COTS exception): `compensating-controls.md`
