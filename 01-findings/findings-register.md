# Module 1 — Cloud Platform & Terraform Security Findings Register

## Scope and approach

This register records a hands-on review of the cloned terragoat Terraform reference target in `reference-target/terraform/`. The review covered AWS, Azure, and GCP resources across storage, database, IAM, compute/networking, logging, encryption, and resilience controls. Findings are intentionally mapped back to the programme scenario: a mostly-AWS government estate today, two landing-zone tiers, Terraform delivered through self-managed GitLab CI/CD, and Azure/GCP onboarding into the same governance model later this year.

The terragoat repository is intentionally vulnerable. The value for this assessment is the pattern match to the audit trigger: public storage, a public and unencrypted database, wildcard service-account-style permissions, inconsistent logging, and missing central detection.

Severity and priority definitions are in `severity-methodology.md`. Finding IDs are stable and must not be renumbered in later modules.

## Executive summary of findings

| Severity | Count | Main themes |
|---|---:|---|
| Critical | 13 | Public data exposure, public databases, hardcoded credentials, wildcard admin rights, exposed Kubernetes control planes |
| High | 13 | Internet-exposed administration, disabled encryption/TLS, disabled detection, weak platform controls |
| Medium | 4 | Key rotation, supply-chain immutability, incomplete audit coverage, CMEK governance gaps |
| Low | 0 | No Low findings were retained because the assessment brief asks for remediation-relevant issues. |

Priority distribution:

| Priority | Count | Treatment |
|---|---:|---|
| P0 — stop exposure | 13 | Immediate remediation or isolation/compensating control |
| P1 — urgent control repair | 13 | Current remediation wave |
| P2 — near-term hardening | 4 | Batched platform hardening |

## Findings

### CLD-001 — AWS S3 data bucket is public and lacks encryption, versioning, and access logging

- **Location:** `reference-target/terraform/aws/s3.tf` — `aws_s3_bucket.data`, `aws_s3_bucket_object.customer_master_data`
- **Severity:** Critical — public storage containing a customer master spreadsheet pattern maps directly to the audit scenario's two public storage buckets.
- **Priority:** P0 — stop exposure
- **Control domain:** Storage security / data protection
- **Risk statement:** Objects in this bucket can be exposed publicly, stored without server-side encryption, overwritten without version recovery, and accessed without a useful access log trail. In the real programme, this is the exact class of issue that triggered escalation: storage buckets with public access controls disabled.
- **Remediation:** Make the bucket private, enable S3 Block Public Access at account and bucket level, enable SSE-KMS with a customer-managed KMS key, enable versioning, enable access logging or S3 server access logs to a central logging bucket, and add a bucket policy denying unencrypted uploads and public ACLs.
- **Effort:** M

### CLD-002 — AWS RDS MySQL instance is public, unencrypted, and has no backups

- **Location:** `reference-target/terraform/aws/db-app.tf` — `aws_db_instance.default`
- **Severity:** Critical — `publicly_accessible = true`, `storage_encrypted = false`, and `backup_retention_period = 0` combine internet exposure, no at-rest protection, and no recovery path.
- **Priority:** P0 — stop exposure
- **Control domain:** Database security / data protection / resilience
- **Risk statement:** An attacker can reach the database endpoint from the internet, attempt credential attacks, extract data stored without encryption at rest, and leave the service unrecoverable after deletion or ransomware. This explicitly matches the scenario audit item: one database instance with encryption-at-rest disabled and public accessibility enabled.
- **Remediation:** Move the instance to private subnets, set `publicly_accessible = false`, enable `storage_encrypted = true` using KMS, set backup retention to at least 7 days with point-in-time recovery, require TLS connections, and restrict security group ingress to application subnets only.
- **Effort:** M

### CLD-003 — AWS IAM user policy grants wildcard service permissions on all resources

- **Location:** `reference-target/terraform/aws/iam.tf` — `aws_iam_user_policy.userpolicy`
- **Severity:** Critical — grants `ec2:*`, `s3:*`, `lambda:*`, and `cloudwatch:*` on `*`, creating broad account compromise potential.
- **Priority:** P0 — stop exposure
- **Control domain:** IAM least privilege / CI identity governance
- **Risk statement:** A user or CI service account with this policy can alter compute, storage, Lambda, and monitoring resources across the AWS account. This is the same failure mode as the scenario's wildcard-permission CI service account: compromise of one automation identity becomes compromise of multiple service domains.
- **Remediation:** Replace wildcard actions and resources with narrowly scoped policies. Use IAM Access Analyzer and CloudTrail last-accessed data to remove unused permissions, split deploy/read/runtime roles, and use GitLab OIDC federation rather than long-lived access keys.
- **Effort:** M

### CLD-004 — AWS provider block contains hardcoded access keys

- **Location:** `reference-target/terraform/aws/providers.tf` — `provider "aws" "plain_text_access_keys_provider"`
- **Severity:** Critical — plaintext cloud credentials in Terraform source are immediately usable and retained in Git history.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / IaC hygiene
- **Risk statement:** Anyone with repository access can recover AWS credentials and authenticate outside approved SSO, MFA, or CI/CD controls.
- **Remediation:** Remove inline `access_key` and `secret_key`, rotate the exposed keys, and authenticate Terraform through GitLab OIDC-to-AWS STS assume role or approved local SSO profiles.
- **Effort:** S

### CLD-005 — AWS EC2 user data embeds cloud credentials

- **Location:** `reference-target/terraform/aws/ec2.tf` — `aws_instance.web_host` `user_data`
- **Severity:** Critical — user data is retrievable through instance metadata and readable by operators with EC2 describe permissions.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / compute hardening
- **Risk statement:** A compromised instance, overly broad EC2 read permission, or console access can expose reusable AWS keys, enabling lateral movement beyond the host.
- **Remediation:** Remove keys from user data, rotate exposed keys, attach a least-privilege IAM instance profile, and retrieve any required application secrets from AWS Secrets Manager or SSM Parameter Store at runtime.
- **Effort:** S

### CLD-006 — AWS Lambda environment variables contain cloud credentials

- **Location:** `reference-target/terraform/aws/lambda.tf` — `aws_lambda_function.analysis_lambda`
- **Severity:** Critical — Lambda environment variables containing access keys are visible through Lambda configuration APIs to principals with read access.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / serverless security
- **Risk statement:** A developer, support role, or attacker with `lambda:GetFunctionConfiguration` can extract credentials and use them outside the Lambda execution boundary.
- **Remediation:** Remove static keys, use the Lambda execution role for AWS access, store external credentials in Secrets Manager with KMS encryption, and restrict `lambda:GetFunctionConfiguration` access.
- **Effort:** S

### CLD-007 — AWS database password is committed as a Terraform variable default

- **Location:** `reference-target/terraform/aws/consts.tf` — `variable "password"`; used by `aws_db_instance.default` and `aws_instance.db_app`
- **Severity:** Critical — committed database password appears in source, plans, and state.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / database authentication
- **Risk statement:** Repository or state access gives direct database credentials, which is especially dangerous because `CLD-002` exposes the database publicly.
- **Remediation:** Remove the default, mark the variable `sensitive = true`, source the password from Secrets Manager or a GitLab masked protected variable, rotate the password, and ensure Terraform state is encrypted and access-controlled.
- **Effort:** S

### CLD-008 — AWS application EC2 writes database credentials into user data and local PHP config

- **Location:** `reference-target/terraform/aws/db-app.tf` — `aws_instance.db_app` `user_data`
- **Severity:** Critical — database endpoint, user name, and password are embedded in bootstrap script content.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / application configuration
- **Risk statement:** Any process or user able to read instance user data or local webroot configuration can recover database credentials and connect to the public RDS instance.
- **Remediation:** Fetch credentials at application start from Secrets Manager or SSM SecureString using the instance role, apply IMDSv2, restrict metadata access, and avoid writing secrets to world-readable application paths.
- **Effort:** M

### CLD-009 — AWS EC2 instance role grants wildcard S3, EC2, and RDS permissions

- **Location:** `reference-target/terraform/aws/db-app.tf` — `aws_iam_role_policy.ec2policy`
- **Severity:** High — a compromised instance receives broad service administration across all resources.
- **Priority:** P1 — urgent control repair
- **Control domain:** IAM least privilege / workload identity
- **Risk statement:** If the application host is compromised, the role can enumerate and modify S3, EC2, and RDS broadly, enabling data exfiltration, persistence, and destructive changes.
- **Remediation:** Scope actions to exact application needs, resource ARNs, and conditions. Separate read/write roles and use AWS Access Analyzer policy generation from CloudTrail activity.
- **Effort:** M

### CLD-010 — Azure custom role grants wildcard actions at subscription scope

- **Location:** `reference-target/terraform/azure/roles.tf` — `azurerm_role_definition.example`
- **Severity:** Critical — `actions = ["*"]` at subscription scope is effectively owner-level capability.
- **Priority:** P0 — stop exposure
- **Control domain:** IAM least privilege / cross-cloud governance
- **Risk statement:** Any principal assigned this role can disable controls, create identities, read or alter data-plane configurations, and delete resources across the subscription. This is the Azure equivalent of the AWS wildcard CI identity issue in `CLD-003`.
- **Remediation:** Replace the custom wildcard role with built-in least-privilege roles or a minimal custom role, narrow assignable scopes, and review role assignments through Microsoft Entra ID Privileged Identity Management.
- **Effort:** M

### CLD-011 — GCP GCS bucket grants anonymous public read

- **Location:** `reference-target/terraform/gcp/gcs.tf` — `google_storage_bucket_iam_binding.allow_public_read` / `google_storage_bucket_iam_binding.binding`
- **Severity:** Critical — `allUsers` with `roles/storage.objectViewer` makes objects readable by unauthenticated internet users.
- **Priority:** P0 — stop exposure
- **Control domain:** Storage security / IAM
- **Risk statement:** Any object placed in the bucket can be downloaded anonymously. This is the GCP expression of the same public-storage misconfiguration class as `CLD-001`.
- **Remediation:** Remove `allUsers`, enable Public Access Prevention and Uniform Bucket-Level Access, bind access only to approved service accounts or groups, and enable data access audit logs for the bucket.
- **Effort:** S

### CLD-012 — GCP Cloud SQL is internet-accessible and backups are disabled

- **Location:** `reference-target/terraform/gcp/big_data.tf` — `google_sql_database_instance.master_instance` / `google_sql_database_instance.postgres`
- **Severity:** Critical — `authorized_networks` includes `0.0.0.0/0` and `backup_configuration.enabled = false`.
- **Priority:** P0 — stop exposure
- **Control domain:** Database security / resilience
- **Risk statement:** The Cloud SQL instance is reachable from any IP and has no automated recovery path after corruption, deletion, or ransomware. It is the GCP analogue of the scenario's public database exposure.
- **Remediation:** Use private IP, remove public authorized networks, enable automated backups and point-in-time recovery, require SSL certificates, and restrict access to application subnets or Cloud SQL Auth Proxy/IAM database authentication.
- **Effort:** M

### CLD-013 — AWS security group exposes SSH to the internet

- **Location:** `reference-target/terraform/aws/ec2.tf` — `aws_security_group.web-node`
- **Severity:** High — port 22 is open from `0.0.0.0/0`.
- **Priority:** P1 — urgent control repair
- **Control domain:** Network security / compute access
- **Risk statement:** Internet-wide SSH access exposes the workload to scanning, brute force, credential stuffing, and exploit attempts against SSH or host configuration.
- **Remediation:** Remove public SSH, use AWS Systems Manager Session Manager or a hardened bastion, and restrict any unavoidable SSH to VPN or bastion security group sources.
- **Effort:** S

### CLD-014 — Azure NSG exposes SSH and RDP from any source

- **Location:** `reference-target/terraform/azure/networking.tf` — `azurerm_network_security_group.bad_sg` / `azurerm_network_security_group.terragoat`
- **Severity:** Critical — management ports 22 and 3389 are open from `*`, and Azure VMs in the same module use password authentication.
- **Priority:** P0 — stop exposure
- **Control domain:** Network security / compute access
- **Risk statement:** Public SSH/RDP creates a direct initial-access path for password spraying, brute force, and exploitation of exposed services. Azure's NSG model expresses this as source prefix `*`, whereas AWS uses CIDR `0.0.0.0/0` and GCP uses `source_ranges`.
- **Remediation:** Remove direct inbound administration, deploy Azure Bastion or VPN/JIT VM access, restrict rules to known management CIDRs, and enable NSG flow logs.
- **Effort:** S

### CLD-015 — GCP firewall allows all TCP ports from the internet

- **Location:** `reference-target/terraform/gcp/networks.tf` — `google_compute_firewall.allow_all` / `google_compute_firewall.allow_ssh`
- **Severity:** Critical — `source_ranges = ["0.0.0.0/0"]` and `ports = ["0-65535"]` expose every TCP service.
- **Priority:** P0 — stop exposure
- **Control domain:** Network security
- **Risk statement:** Any VM targeted by the rule is reachable on every TCP port from the public internet, making every running service part of the external attack surface.
- **Remediation:** Delete the allow-all rule, create explicit least-privilege firewall rules per service, use IAP TCP forwarding for administration, and add hierarchical firewall policy guardrails.
- **Effort:** S

### CLD-016 — GCP GKE cluster disables logging/monitoring and exposes the control plane with legacy ABAC

- **Location:** `reference-target/terraform/gcp/gke.tf` — `google_container_cluster.workload_cluster` / `google_container_cluster.primary`
- **Severity:** Critical — `logging_service = "none"`, `monitoring_service = "none"`, `enable_legacy_abac = true`, and master authorized networks include `0.0.0.0/0`.
- **Priority:** P0 — stop exposure
- **Control domain:** Kubernetes security / logging and monitoring
- **Risk statement:** The Kubernetes API is reachable from the internet, legacy ABAC weakens authorization, and no managed logs or metrics are available to detect misuse. This directly supports the scenario's concern that no centralised detection or alerting exists.
- **Remediation:** Disable legacy ABAC, enable Cloud Logging and Cloud Monitoring for GKE, restrict master authorized networks or use a private cluster, enable Workload Identity, and route audit logs into the central SIEM.
- **Effort:** M

### CLD-017 — Azure AKS has RBAC disabled, dashboard enabled, and monitoring disabled

- **Location:** `reference-target/terraform/azure/aks.tf` — `azurerm_kubernetes_cluster.k8s_cluster` / `azurerm_kubernetes_cluster.aks`
- **Severity:** Critical — Kubernetes RBAC is disabled, the legacy dashboard is enabled, and OMS/Container Insights is disabled.
- **Priority:** P0 — stop exposure
- **Control domain:** Kubernetes security / logging and monitoring
- **Risk statement:** Cluster users or compromised workloads can receive excessive permissions, dashboard exposure increases attack surface, and central telemetry is absent. This is the Azure counterpart to `CLD-016`.
- **Remediation:** Enable Azure RBAC and Kubernetes RBAC, disable the dashboard, enable Azure Monitor Container Insights, integrate cluster access with Microsoft Entra ID, and restrict API server access.
- **Effort:** M

### CLD-018 — AWS EBS volume and snapshot are unencrypted

- **Location:** `reference-target/terraform/aws/ec2.tf` — `aws_ebs_volume.web_host_storage`, `aws_ebs_snapshot.example_snapshot`
- **Severity:** High — block storage and derived snapshot lack encryption controls.
- **Priority:** P1 — urgent control repair
- **Control domain:** Storage encryption / key management
- **Risk statement:** Host data, application files, and potentially bootstrap secrets can persist in plaintext on both the live volume and snapshot copy.
- **Remediation:** Enable default EBS encryption at account level, set `encrypted = true` for volumes, use a customer-managed KMS key for sensitive workloads, and recreate or re-encrypt existing snapshots.
- **Effort:** S

### CLD-019 — AWS Neptune cluster disables storage encryption

- **Location:** `reference-target/terraform/aws/neptune.tf` — `aws_neptune_cluster.default`
- **Severity:** High — `storage_encrypted = false` leaves graph database data unencrypted at rest.
- **Priority:** P1 — urgent control repair
- **Control domain:** Database encryption / key management
- **Risk statement:** Relationship data in the graph database can be exposed if storage or snapshots are mishandled, copied, or accessed by a privileged insider.
- **Remediation:** Set `storage_encrypted = true`, specify a customer-managed KMS key where required, and rebuild/migrate the cluster because encryption is normally set at creation time.
- **Effort:** M

### CLD-020 — Azure managed disk encryption is explicitly disabled

- **Location:** `reference-target/terraform/azure/storage.tf` — `azurerm_managed_disk.example` / `azurerm_managed_disk.source`
- **Severity:** High — `encryption_settings { enabled = false }` disables disk encryption on block storage.
- **Priority:** P1 — urgent control repair
- **Control domain:** Storage encryption / key management
- **Risk statement:** VM or application data on the disk is not protected by the expected encryption-at-rest control, and snapshot/copy operations inherit weak posture.
- **Remediation:** Enable Azure Disk Encryption or platform-managed encryption with customer-managed keys from Key Vault, and enforce disk encryption through Azure Policy.
- **Effort:** M

### CLD-021 — GCP compute disk lacks customer-managed key protection

- **Location:** `reference-target/terraform/gcp/instances.tf` — `google_compute_disk.unencrypted_disk` / `google_compute_disk.compute_disk`
- **Severity:** Medium — GCP default encryption exists, but there is no CMEK separation of duties or revocation control.
- **Priority:** P2 — near-term hardening
- **Control domain:** Key management / storage encryption
- **Risk statement:** Sensitive workloads cannot demonstrate customer control over encryption keys, rotation, revocation, or separation between platform administrators and data custodians.
- **Remediation:** Add `disk_encryption_key` referencing a Cloud KMS key for sensitive disks and enforce CMEK through organisation policy where required.
- **Effort:** M

### CLD-022 — AWS KMS key has no automatic rotation

- **Location:** `reference-target/terraform/aws/kms.tf` — `aws_kms_key.logs_key`
- **Severity:** Medium — long-lived KMS key material increases exposure if key access is compromised.
- **Priority:** P2 — near-term hardening
- **Control domain:** Cryptographic key management
- **Risk statement:** A key used for logs or other data remains valid indefinitely, reducing the programme's ability to bound the impact of key compromise.
- **Remediation:** Set `enable_key_rotation = true`, define key owners and deletion windows, and include KMS key policy review in platform guardrails.
- **Effort:** S

### CLD-023 — Azure and GCP databases do not enforce encrypted connections

- **Location:** `reference-target/terraform/azure/sql.tf` — `azurerm_mysql_server.example`, `azurerm_postgresql_server.example`; `reference-target/terraform/gcp/big_data.tf` — `google_sql_database_instance.master_instance` / `postgres`
- **Severity:** High — Azure explicitly disables SSL enforcement and GCP lacks a `require_ssl` control.
- **Priority:** P1 — urgent control repair
- **Control domain:** Encryption in transit / database security
- **Risk statement:** Database credentials and query data can traverse networks without TLS enforcement. The same control gap looks different by provider: Azure uses `ssl_enforcement_enabled = false`, while GCP requires adding SSL enforcement inside Cloud SQL IP configuration.
- **Remediation:** Enable SSL/TLS enforcement on Azure MySQL/PostgreSQL, configure GCP Cloud SQL to require SSL certificates, and update application connection strings and drivers accordingly.
- **Effort:** M

### CLD-024 — Azure SQL threat detection disables SQL injection and data exfiltration alerts

- **Location:** `reference-target/terraform/azure/sql.tf` — `azurerm_mssql_server_security_alert_policy.example`; `reference-target/terraform/azure/mssql.tf` — `azurerm_mssql_server_security_alert_policy.alertpolicy1` through `alertpolicy7`
- **Severity:** High — the most relevant database attack detections are explicitly disabled.
- **Priority:** P1 — urgent control repair
- **Control domain:** Detection and response / database monitoring
- **Risk statement:** SQL injection and data exfiltration attempts against SQL databases can occur without the expected Defender alert path, undermining incident response and auditability.
- **Remediation:** Remove `Sql_Injection` and `Data_Exfiltration` from `disabled_alerts`, enable Microsoft Defender for SQL, route alerts to the SOC workflow, and test alert generation.
- **Effort:** S

### CLD-025 — Azure SQL and MSSQL admin passwords are hardcoded across multiple servers

- **Location:** `reference-target/terraform/azure/sql.tf` — `azurerm_sql_server.example`, `azurerm_postgresql_server.example`; `reference-target/terraform/azure/mssql.tf` — `azurerm_mssql_server.mssql1` through `mssql7`
- **Severity:** Critical — repeated committed admin passwords create broad database compromise potential.
- **Priority:** P0 — stop exposure
- **Control domain:** Secrets management / database administration
- **Risk statement:** Anyone with repository or state access can recover administrator credentials, and password reuse across seven MSSQL servers means one leak compromises multiple databases.
- **Remediation:** Rotate all database administrator credentials, source secrets from Azure Key Vault or a CI/CD secret store, mark Terraform variables sensitive, and avoid shared passwords across servers.
- **Effort:** S

### CLD-026 — GCP BigQuery dataset grants reader access to all authenticated users

- **Location:** `reference-target/terraform/gcp/big_data.tf` — `google_bigquery_dataset.dataset` / dataset access block with `special_group = "allAuthenticatedUsers"`
- **Severity:** High — any authenticated Google identity can read the dataset, which is broader than the programme boundary.
- **Priority:** P1 — urgent control repair
- **Control domain:** Data access governance / IAM
- **Risk statement:** Analytics or operational datasets may be visible to identities that are not part of the programme, enabling quiet data discovery and exfiltration.
- **Remediation:** Remove `allAuthenticatedUsers`, grant `roles/bigquery.dataViewer` only to approved groups or service accounts, add IAM Conditions where useful, and enable BigQuery data access logs.
- **Effort:** S

### CLD-027 — AWS RDS/Aurora clusters have weak backup retention settings

- **Location:** `reference-target/terraform/aws/rds.tf` — `aws_rds_cluster.app1-rds-cluster` and related `aws_rds_cluster.app*` resources
- **Severity:** High — at least one cluster sets `backup_retention_period = 0`, with inconsistent retention across similar clusters.
- **Priority:** P1 — urgent control repair
- **Control domain:** Backup and resilience / database protection
- **Risk statement:** Corruption, deletion, or ransomware against affected clusters can cause permanent data loss or recovery gaps, undermining go-live sign-off for critical workloads.
- **Remediation:** Set a baseline retention policy of at least 7 days, with 15–35 days for regulated workloads, enable point-in-time recovery, and enforce through Terraform module defaults and AWS Config rules.
- **Effort:** S

### CLD-028 — Azure network and activity logging are incomplete or disabled

- **Location:** `reference-target/terraform/azure/networking.tf` — `azurerm_network_watcher_flow_log.flow_log`; `reference-target/terraform/azure/logging.tf` — `azurerm_monitor_log_profile.logging_profile`
- **Severity:** High — NSG flow logs are disabled and activity logging is incomplete.
- **Priority:** P1 — urgent control repair
- **Control domain:** Logging and monitoring / incident response
- **Risk statement:** Network-level evidence for brute force, lateral movement, and exfiltration is absent, and management-plane actions are not consistently captured. This maps directly to the scenario's inconsistent audit logging coverage.
- **Remediation:** Enable Network Watcher flow logs with retention, send logs to Log Analytics/Event Hub/SIEM, capture write/delete/action categories, and standardise diagnostic settings through Azure Policy.
- **Effort:** S

### CLD-029 — Azure Defender for Cloud is Free tier and notifications are disabled

- **Location:** `reference-target/terraform/azure/security_center.tf` — `azurerm_security_center_subscription_pricing.pricing`, `azurerm_security_center_contact.contact`
- **Severity:** High — reduced threat protection plus disabled notifications means findings are unlikely to reach responders.
- **Priority:** P1 — urgent control repair
- **Control domain:** CSPM / detection and response
- **Risk statement:** Even where Microsoft detects risks, alerts are not sent to security contacts or admins; the programme cannot claim centralised detection and alerting coverage.
- **Remediation:** Enable Defender plans for Servers, SQL, Storage, Containers, and relevant workload types; turn on `alert_notifications` and `alerts_to_admins`; integrate with Sentinel or the existing SIEM.
- **Effort:** S

### CLD-030 — AWS ECR repository allows mutable image tags

- **Location:** `reference-target/terraform/aws/ecr.tf` — `aws_ecr_repository.repository`
- **Severity:** Medium — mutable tags undermine image provenance but require push access to exploit.
- **Priority:** P2 — near-term hardening
- **Control domain:** Supply-chain security / container registry governance
- **Risk statement:** A compromised CI token or developer credential can overwrite a trusted tag such as `latest` or `prod`, causing downstream deployments to pull a different image than the one reviewed.
- **Remediation:** Set `image_tag_mutability = "IMMUTABLE"`, deploy by digest, require ECR image scanning/Inspector, and sign images with Sigstore Cosign or AWS Signer in GitLab CI.
- **Effort:** S

## Cross-cloud pattern called out for governance

The same misconfiguration class appears differently across providers and therefore needs provider-native guardrails rather than a single text pattern:

- **Public storage:** AWS uses S3 bucket ACL/policy/Public Access Block controls (`CLD-001`), GCP uses IAM members such as `allUsers` (`CLD-011`), and Azure must enforce storage account public access disablement plus private endpoints and container access policy.
- **Public network exposure:** AWS security groups use CIDRs (`CLD-013`), Azure NSGs use `source_address_prefix = "*"` (`CLD-014`), and GCP firewall rules use `source_ranges` plus broad port ranges (`CLD-015`).
- **Database encryption in transit:** Azure exposes explicit `ssl_enforcement_enabled` flags, while GCP requires Cloud SQL SSL settings (`CLD-023`).
- **Logging gaps:** Azure disables flow logs and notifications through separate Network Watcher and Defender resources (`CLD-028`, `CLD-029`), while GCP GKE disables telemetry on the cluster resource itself (`CLD-016`).

This is why later pipeline modules should combine Checkov/Trivy IaC rules with provider-specific OPA policies and cloud-native controls such as AWS Config, Azure Policy, and Google Cloud Config Validator.
