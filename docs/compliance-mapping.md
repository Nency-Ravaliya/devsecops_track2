# Module 10 — Compliance Mapping

## Approach

This module does not have access to the programme's actual internal compliance clauses. Instead, it demonstrates the **mapping methodology**: how findings from Module 1 map to plausible compliance domains, what evidence demonstrates compliance, and how exceptions are documented. This methodology is directly applicable when the real clause text is available.

## Finding-to-compliance-domain mapping

### CLD-001 — AWS S3 data bucket is public and lacks encryption, versioning, and access logging

| Aspect | Detail |
|---|---|
| **Compliance domains** | Data protection (data at rest must be encrypted); access control (data must not be publicly accessible); audit trail (access must be logged); data integrity (versioning must prevent silent overwrites). |
| **Relevant control families** | Access control, data protection, audit and accountability, system and information integrity. |
| **Evidence to demonstrate compliance** | S3 bucket policy showing `Deny` for unencrypted uploads; SSE-KMS configuration with CMK ARN; S3 Block Public Access enabled at account and bucket level; access logging enabled to a central logging bucket; versioning enabled. All verified through Terraform state, AWS Config rules, and Checkov scan output from the CI pipeline. |
| **Evidence to justify exception** | If the COTS exception applies to this bucket type: exception register entry (EXC-001) with CISO sign-off, compensating controls documentation, expiry date, and quarterly review log. |
| **How it's enforced** | OPA policy in CI pipeline denies any `aws_s3_bucket` without encryption and public access block. AWS Config rule `s3-bucket-public-read-prohibited` and `s3-bucket-server-side-encryption-enabled` provide continuous compliance monitoring. |

### CLD-002 — AWS RDS MySQL instance is public, unencrypted, and has no backups

| Aspect | Detail |
|---|---|
| **Compliance domains** | Data protection (encryption at rest and in transit); network security (no public exposure of databases); data availability (backups for recovery); access control (database access restricted to authorised parties). |
| **Relevant control families** | Data protection, network security, data availability, access control. |
| **Evidence to demonstrate compliance** | `publicly_accessible = false` in Terraform state; `storage_encrypted = true` with KMS key ARN; `backup_retention_period >= 7`; security group rules showing ingress only from application subnet; `rds.force_ssl = 1` in parameter group; RDS audit logs shipping to CloudWatch. |
| **Evidence to justify exception** | Not applicable — this is a standard workload, not the COTS exception. |
| **How it's enforced** | OPA policy denies `aws_db_instance` without encryption, public access disabled, and backup retention. AWS Config rules `rds-storage-encrypted`, `rds-snapshot-encrypted`, `rds-multi-az-support`. |

### CLD-003 — AWS IAM user policy grants wildcard service permissions on all resources

| Aspect | Detail |
|---|---|
| **Compliance domains** | Access control (least privilege); identity management (no unnecessary permissions); accountability (all access must be attributable to a specific identity). |
| **Relevant control families** | Access control, identity management, audit and accountability. |
| **Evidence to demonstrate compliance** | IAM policy document showing only explicit, least-privilege actions on scoped resource ARNs. IAM Access Analyzer report showing no unused permissions. CloudTrail logs showing all actions attributable to specific IAM roles (not users). OIDC federation logs showing short-lived credential issuance. |
| **Evidence to justify exception** | None — wildcard IAM is never justifiable. |
| **How it's enforced** | Checkov CKV_AWS_1/62 in CI pipeline hard-fail. OPA policy denies any IAM policy with `Action: "*"`. AWS IAM Access Analyzer runs monthly to detect unused permissions. |

### CLD-012 — GCP Cloud SQL instance is internet-accessible and backups are disabled

| Aspect | Detail |
|---|---|
| **Compliance domains** | Network security (no public database exposure); data availability (backup for recovery); data protection (encrypted connections). |
| **Relevant control families** | Network security, data availability, data protection. |
| **Evidence to demonstrate compliance** | `ipv4_enabled = false` in Terraform state (private IP only); `authorized_networks` empty or restricted to private CIDRs; `backup_configuration.enabled = true` with appropriate `start_time`; `settings.ip_configuration.require_ssl = true`. |
| **Evidence to justify exception** | None — this is a standard workload. |
| **How it's enforced** | OPA policy denies `google_sql_database_instance` with public IP or no backup. GCP Config Validator policy `compute/sql_public_ip`. |

### CLD-025 — Azure SQL/MSSQL admin passwords are hardcoded across multiple servers

| Aspect | Detail |
|---|---|
| **Compliance domains** | Credential management (secrets must not be committed to source control); access control (admin credentials must be unique per system); accountability (credential usage must be traceable). |
| **Relevant control families** | Credential management, access control, audit and accountability. |
| **Evidence to demonstrate compliance** | Git history scan showing no committed passwords (Gitleaks passing in CI). Azure Key Vault audit log showing secret access events. Each MSSQL server referencing a unique Key Vault secret. No shared passwords across servers. Rotation policy on Key Vault secrets (90-day maximum age). |
| **Evidence to justify exception** | None — committed credentials are never justifiable. |
| **How it's enforced** | Gitleaks in CI pipeline (hard-fail). OPA policy denies Terraform with hardcoded `administrator_login_password` values. Azure Policy: `keyvault-secret-expiry` ensures secrets have rotation policies. |

## Single policy-as-code framework across AWS, Azure, and GCP

### The challenge

The programme needs to enforce the same control (e.g., "no storage bucket may be publicly accessible") across AWS S3, Azure Blob Storage, and GCP Cloud Storage. Maintaining three separate rule sets is operationally expensive and risks inconsistency.

### The solution: OPA/Conftest with provider-specific input normalization

OPA/Conftest evaluates Rego policies against Terraform plan output or provider state. The key insight: Terraform's `terraform show -json tfplan` produces a provider-agnostic resource graph that OPA can evaluate. A single Rego policy can express the intent, while provider-specific Rego helpers normalize the resource attributes.

### Concrete example: "No public storage access"

The control is: **no storage bucket or container may grant access to unauthenticated users or the public internet.**

**Rego policy (shared across all providers):**

```rego
# policy/storage_no_public_access.rego
package main

import rego.v1

# Normalize all storage resources to a common shape
storage_resources contains result if {
    some resource in input.planned_values.root_module.resources
    result := normalize_storage(resource)
}

normalize_storage(resource) := normalized if {
    resource.type == "aws_s3_bucket"
    normalized := {
        "provider": "aws",
        "name": resource.name,
        "public": is_s3_public(resource),
    }
}

normalize_storage(resource) := normalized if {
    resource.type == "azurerm_storage_account"
    normalized := {
        "provider": "azure",
        "name": resource.name,
        "public": is_azure_storage_public(resource),
    }
}

normalize_storage(resource) := normalized if {
    resource.type == "google_storage_bucket"
    normalized := {
        "provider": "gcp",
        "name": resource.name,
        "public": is_gcs_public(resource),
    }
}

# --- Provider-specific detection logic ---

is_s3_public(resource) if {
    resource.values.acl == "public-read"
}

is_s3_public(resource) if {
    resource.values.acl == "public-read-write"
}

is_s3_public(resource) if {
    some binding in resource.values.policy
    binding.principal == "*"
    binding.action == "s3:GetObject"
}

is_azure_storage_public(resource) if {
    resource.values.allow_blob_public_access == true
}

is_gcs_public(resource) if {
    some member in resource.values.iam_configuration.uniform_bucket_level_access
    member.enabled == false
}

# --- The control ---

deny[msg] if {
    some resource in storage_resources
    resource.public == true
    msg := sprintf("VIOLATION: %s (%s) has public access enabled", [resource.name, resource.provider])
}
```

**How it works in the pipeline (from Module 2):**

```yaml
# In .gitlab-ci-example.yml
opa-conftest:
  stage: iac-scan
  image: openpolicyagent/conftest:latest
  script:
    - conftest test --policy policy/ ${TF_ROOT}
  # This single policy evaluates against AWS, Azure, and GCP resources
  # in the same Terraform plan, regardless of which provider they use.
```

**Why this works:** When a Terraform configuration contains both `aws_s3_bucket` and `google_storage_bucket` resources (as terragoat does), the OPA policy normalizes both into a common shape and evaluates the same control against both. One policy, one rule, three providers.

### Additional cross-cloud control examples

| Control | AWS resource | Azure resource | GCP resource | Rego rule |
|---|---|---|---|---|
| No public database exposure | `aws_db_instance` with `publicly_accessible = true` | `azurerm_sql_server` with `allow_access_to_azure_services = true` | `google_sql_database_instance` with `ipv4_enabled = true` | `deny` if `resource.public == true` |
| Encryption at rest required | `aws_s3_bucket` without `server_side_encryption_configuration` | `azurerm_storage_account` without encryption | `google_storage_bucket` without CMEK | `deny` if `resource.encrypted == false` |
| No wildcard IAM | `aws_iam_user_policy` with `Action: "*"` | `azurerm_role_definition` with `actions = ["*"]` | `google_project_iam_binding` with `role = "roles/owner"` | `deny` if `resource.wildcard == true` |

## Exception documentation for compliance

When a finding cannot be remediated (e.g., the COTS encryption exception), the compliance mapping documents:

1. **Which control is not met** — mapped to the specific compliance domain.
2. **Why** — vendor limitation, documented in the exception register.
3. **What compensating controls exist** — from `../07-remediation/compensating-controls.md`.
4. **Residual risk** — rated using the severity methodology from `../01-findings/severity-methodology.md`.
5. **Who accepted the risk** — CISO role, with a signed acceptance form.
6. **When the exception expires** — maximum 12 months, with quarterly re-review.

This documentation is auditable: the exception register is version-controlled, the risk acceptance is in the GRC tool, and the compensating controls are verified through CSPM scans (Module 6).

## Cross-references

- Findings register (finding IDs): `../01-findings/findings-register.md`
- Pipeline (OPA enforcement): `../02-pipeline-supply-chain/pipeline-design.md`
- Compensating controls (exception handling): `../07-remediation/compensating-controls.md`
- Detection and IR (compliance evidence from logs): `../06-detection-ir/monitoring-ir-plan.md`
