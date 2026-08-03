# Module 5 — Data Protection, Encryption & Key Management

## Context

The audit trigger explicitly found a database instance with encryption-at-rest disabled and public accessibility enabled (`CLD-002`). Several more findings address encryption gaps: S3 bucket without SSE (`CLD-001`), Neptune cluster without storage encryption (`CLD-019`), EBS volume/snapshot unencrypted (`CLD-018`), Azure managed disk encryption disabled (`CLD-020`), GCP compute disk without CMEK (`CLD-021`), databases not enforcing TLS (`CLD-023`), and KMS key without rotation (`CLD-022`). The programme also has a hard constraint: a COTS financial reconciliation tool whose vendor driver cannot operate with storage encryption enabled.

This module designs an encryption and key management approach that addresses all of these, including the COTS exception.

## Encryption strategy

### Encryption at rest

Every data store gets encryption at rest by default, with no opt-out for new deployments. The enforcement mechanism is:

1. **Cloud-native default encryption** is enabled at the account/subscription/project level (AWS S3 default encryption, Azure Storage service-level encryption, GCP default encryption).
2. **Customer-managed keys (CMK)** are required for all Tier 1 and Tier 2 workloads handling sensitive data.
3. **Platform-managed keys** are acceptable for Tier 3 internal workloads only.
4. **Policy-as-code enforcement** — OPA/Conftest policies in the CI pipeline (`../02-pipeline-supply-chain/pipeline-design.md`) block any Terraform that creates a storage or database resource without encryption enabled. Checkov checks CKV_AWS_19 (S3), CKV_AWS_16 (RDS), CKV_AZURE_3 (storage), CKV_GCP_28 (GCS) hard-fail at the pipeline gate.

| Resource type | Target encryption | Enforcement |
|---|---|---|
| S3 buckets | SSE-KMS with CMK | OPA policy: deny `aws_s3_bucket` without `server_side_encryption_configuration`. Account-level default encryption as fallback. |
| EBS volumes | `encrypted = true`, CMK per workload | Account-level `aws_ebs_encryption_by_default = true`. |
| RDS/Aurora | `storage_encrypted = true`, CMK | OPA policy: deny `aws_db_instance` / `aws_rds_cluster` without `storage_encrypted = true`. |
| Neptune | `storage_encrypted = true` | OPA policy (same pattern). |
| Azure managed disks | Platform-managed or CMK | Azure Policy: enforce disk encryption. |
| Azure Storage | Service encryption + CMK for sensitive data | Azure Policy: deny storage accounts without encryption. |
| GCP persistent disks | CMEK for sensitive workloads | Org policy: require CMEK on projects handling sensitive data. |
| GCP GCS | CMEK or dual-region default encryption | Bucket-level policy via OPA or GCP Org Policy. |

### Encryption in transit

Every connection between components uses TLS 1.2 or higher. No exceptions.

| Path | Mechanism | Enforcement |
|---|---|---|
| Client → Load balancer | TLS 1.2+ termination at edge (ALB/Azure App Gateway/GCP Cloud CDN). | Terraform: `ssl_policy` on ALB set to ELBSecurityPolicy-TLS13-1-2-2021-06. App Gateway uses `WAF_v2` with TLS 1.2 listener. |
| Load balancer → Application | TLS re-encryption or mTLS (Istio service mesh). | Service mesh mTLS enforced by policy. |
| Application → Database | TLS enforced at database level. `CLD-023` fix: Azure `ssl_enforcement = Enabled`, GCP `require_ssl = true`, AWS RDS parameter `rds.force_ssl = 1`. | Database parameter enforcement + application connection string configuration. |
| Application → Object storage | HTTPS only. S3 bucket policy denies `aws:SecureTransport = false`. | OPA policy: deny S3 buckets without a deny-insecure-transport bucket policy. |
| Cross-account / Cross-cloud | Private connectivity (Transit Gateway, Private Link) + mTLS. | Network design in `../04-network-zero-trust/network-design.md`. |

### Encryption for the COTS exception

The COTS financial reconciliation tool cannot operate with storage encryption enabled. The specific constraint: the vendor's connection driver does not support encrypted storage.

**Treatment (detailed in `../07-remediation/compensating-controls.md`):**

- The workload's storage bucket/database is the **only** resource in the programme exempt from encryption at rest.
- **Interim state (compliance deadline):** Compensating controls apply — private network placement, strict IAM, access logging, network-level monitoring. See Module 8.
- **Target state:** The vendor ships an updated driver supporting encryption. The exception expires on a fixed date (maximum 12 months from go-live, or vendor's next major release, whichever comes first).
- **The exception is recorded in a formal exception register** with a named owner, expiry date, compensating controls, and quarterly re-review. It is not a blanket precedent.

## Key management approach

### Centralised vs per-cloud KMS

**Decision: use each cloud's native KMS, governed by a single policy framework.**

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| Single cross-cloud KMS (e.g., HashiCorp Vault as KMS for all clouds) | Unified key lifecycle. One system to operate. | Vault operational overhead. No native cloud integration for envelope encryption. Vendor lock-in to Vault. Adds latency to cloud API calls. | Rejected for primary KMS. Vault is valuable for application secrets, not cloud KMS operations. |
| Per-cloud native KMS (AWS KMS, Azure Key Vault, GCP Cloud KMS) | Native envelope encryption. No latency. Managed service — no operational burden. Supports cloud-native features (S3 SSE-KMS, disk encryption, etc.). | Three key management surfaces to govern. Key policies are cloud-specific. | **Selected.** Governance is applied through OPA policies in CI and cloud-native key policies, not by centralising the KMS itself. |

**Why per-cloud wins:** The blast radius argument cuts both ways. A single cross-cloud KMS means one compromise affects all clouds. Per-cloud KMS means key compromise is isolated to one cloud. Since cross-cloud runtime traffic is not routed through a single path (`../04-network-zero-trust/network-design.md`), there is no operational justification for a single KMS.

### Key hierarchy per cloud

**AWS:**

```
Account-level CMK (aws/kms key policy)
├── S3 encryption key (per workload)
├── EBS encryption key (per workload or per-account default)
├── RDS encryption key (per workload)
├── Secrets Manager encryption key (per region)
└── CloudWatch Logs encryption key (per region)
```

**Azure:**

```
Resource Group per workload
├── Key Vault per workload (or shared per environment)
│   ├── Key: disk-encryption-key
│   ├── Key: storage-encryption-key
│   └── Secret: database-credentials
└── Azure Disk Encryption (uses Key Vault keys)
```

**GCP:**

```
Project per workload (or per environment)
├── Cloud KMS key ring per environment
│   ├── Key: storage-encryption-key
│   ├── Key: disk-encryption-key
│   └── Key: database-encryption-key
└── CMEK bindings on buckets, disks, and Cloud SQL
```

### Key rotation

| Cloud | Rotation | Policy |
|---|---|---|
| AWS | Automatic annual rotation via `enable_key_rotation = true` on all CMKs (`CLD-022` fix). Manual rotation available on demand. | OPA policy: deny any `aws_kms_key` without `enable_key_rotation = true`. |
| Azure | Key Vault keys support automatic rotation via `rotation_policy`. | Azure Policy: require rotation policy on Key Vault keys used for disk/storage encryption. |
| GCP | Cloud KMS supports automatic rotation with configurable period. | Org policy or Terraform module default: set rotation period to 90 days for primary keys. |

### BYOK / HYOK decision

| Model | What it means | Where it applies |
|---|---|---|
| **BYOK (Bring Your Own Key)** | Customer generates the key in their own KMS and imports it into the cloud provider's KMS for use. | Appropriate for workloads where the programme needs the ability to revoke the cloud provider's access to the key material. Recommended for Tier 1 workloads handling citizen or financial data. |
| **HYOK (Hold Your Own Key)** | Customer retains exclusive control of the key material. Cloud provider never has access to the plaintext key. | Overkill for this programme. HYOK adds significant operational complexity (key escrow, manual key loading) and is typically required only for the most restrictive sovereign cloud requirements. |
| **Platform-managed / provider KMS** | Cloud provider manages the key lifecycle entirely. | Acceptable for Tier 3 internal workloads. Not acceptable for Tier 1 or Tier 2 with sensitive data. |

**Recommendation:** BYOK for Tier 1 (citizen data, financial data, authentication). CMK within native KMS for Tier 2. Platform-managed for Tier 3. HYOK is not warranted in this programme — the operational cost exceeds the residual risk reduction given that cross-cloud runtime isolation is already enforced.

## Data classification and control mapping

Not every workload needs the same controls. A lightweight classification drives encryption, backup, and access decisions:

| Classification | Examples in this programme | Encryption at rest | Encryption in transit | Backup | Access control |
|---|---|---|---|---|---|
| **Restricted** | Citizen PII, financial reconciliation data, authentication secrets, database credentials | BYOK or CMK. No exceptions. | TLS 1.2+ everywhere. mTLS between services. | Cross-region, immutable, encrypted backups. | IAM conditions, resource-level policies, no public access. |
| **Sensitive** | Internal business data, operational analytics, application configs with embedded credentials | CMK. | TLS 1.2+. | Regional, encrypted backups. | Role-based, workload-scoped. |
| **Internal** | Public-facing marketing content, non-sensitive metadata, dev/test data | Platform-managed encryption. | TLS 1.2+. | Best-effort backup. | Standard role-based. |
| **Public** | Published documentation, open datasets | No encryption required (data is public). | TLS 1.2+ for transport integrity. | Versioning for integrity, not confidentiality. | Public read. |

Classification is recorded as a tag on every cloud resource (`classification: restricted|sensitive|internal|public`) and enforced through OPA policies that map classification to encryption requirements.

## Data residency and sovereignty

For a government programme, data residency is a governance concern, not just a technical one. The principled approach:

1. **Data stays in the region it was collected in** unless a documented cross-border transfer mechanism exists. Cloud regions are chosen to match the data residency requirement, not for cost optimisation.
2. **Encryption keys for Restricted data should reside in the same geopolitical region as the data.** This means AWS KMS keys in the data's region, Azure Key Vault in the data's region, GCP Cloud KMS in the data's region. Cross-region key replication is not permitted for Restricted data.
3. **Backups follow data residency.** Cross-region backups are permitted within the same geopolitical boundary (e.g., EU to EU, UK to UK). Cross-boundary backup replication requires a documented legal basis and DPO approval.
4. **Cloud provider support access is controlled.** Customer Lockbox / Support Access Approval ensures the cloud provider cannot access data without explicit customer approval for each support case.
5. **Logging and audit trails inherit the data's residency.** CloudTrail, Activity Logs, and Audit Logs are stored in the same region as the workload. Centralised SIEM ingestion may cross regions for operational efficiency, but raw logs must remain in-region.

**Not invented here:** These are standard government data residency principles. The specific legislation (e.g., GDPR, UK GDPR, Australian Privacy Act) determines the exact regional boundaries, but the technical architecture supports any region-based constraint by pinning resources, keys, and backups to the correct region through Terraform variables.

## Module 1 findings addressed

| Finding | How this design addresses it |
|---|---|
| `CLD-001` (S3 public, no encryption) | Default encryption + OPA deny policy + bucket policy deny insecure transport. |
| `CLD-002` (RDS public, no encryption) | `storage_encrypted = true` enforced by OPA. Network design makes public access impossible. |
| `CLD-007` (DB password committed) | Secrets in Key Vault / Secrets Manager. Not in Terraform state in plaintext. |
| `CLD-018` (EBS unencrypted) | Account-level EBS encryption default + OPA policy. |
| `CLD-019` (Neptune unencrypted) | OPA policy: deny Neptune without `storage_encrypted = true`. |
| `CLD-020` (Azure disk encryption disabled) | Azure Policy: enforce disk encryption. |
| `CLD-021` (GCP disk no CMEK) | CMEK requirement for sensitive workloads via org policy. |
| `CLD-022` (KMS no rotation) | `enable_key_rotation = true` enforced by OPA. |
| `CLD-023` (No TLS on databases) | TLS enforcement at database level + application connection configuration. |

## Cross-references

- Findings register: `../01-findings/findings-register.md`
- Pipeline (OPA encryption policies): `../02-pipeline-supply-chain/pipeline-design.md`
- Identity governance (key access via IAM): `../03-identity-governance/cross-cloud-iam-design.md`
- Network design (private endpoints, no public access to data): `../04-network-zero-trust/network-design.md`
- Compensating controls (COTS exception): `../07-remediation/compensating-controls.md`
- Architecture: `../10-architecture/architecture-narrative.md`
