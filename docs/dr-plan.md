# Module 11 — Resilience & Disaster Recovery Across Clouds

## Representative workload: db-app (financial reconciliation)

This is the same workload modelled in the threat model (`../08-threat-model/threat-model.md`). It contains the programme's most critical data: financial reconciliation records.

### RTO and RPO targets

| Metric | Target | Justification |
|---|---|---|
| **RPO (Recovery Point Objective)** | 1 hour | Financial reconciliation data must not lose more than 1 hour of transactions. 1-hour backup intervals are achievable with RDS automated backups. |
| **RTO (Recovery Time Objective)** | 4 hours | The reconciliation tool can tolerate up to 4 hours of downtime before manual workarounds become unmanageable. This allows time for automated Multi-AZ failover (seconds) or manual restore from backup (hours). |

### Architecture choices to meet these targets

1. **Multi-AZ RDS** — automatic failover in under 30 seconds for AZ-level failures. This handles the common case (single AZ outage) without human intervention and meets the RPO/RTO trivially.
2. **Automated backups with 7-day retention** — point-in-time recovery to any second within the retention window. Meets the 1-hour RPO.
3. **Cross-region manual snapshot replication** — for region-level failures (rare but possible). Snapshots are copied to a DR region with a 24-hour RPO. The 4-hour RTO is achievable because a snapshot restore + DNS update takes approximately 2–3 hours for a database of this size.
4. **Terraform state in S3 with cross-region replication** — the infrastructure is rebuildable from code. The DR region has a warm standby VPC (subnets and routing exist, no compute running). Scaling up compute is a `terraform apply` away.

## Backup approach across resource types

### Storage (S3 / GCS / Azure Blob)

| Resource | Backup mechanism | Encryption | Access control |
|---|---|---|---|
| S3 buckets | Versioning enabled (protects against accidental deletion). Cross-region replication to DR region for Tier 1 workloads. | SSE-KMS with CMK. DR replica encrypted with DR-region CMK. | Bucket policy: only the application role and the CI deploy role can write. DR replica: read-only for disaster recovery role only. |
| GCS buckets | Object versioning. Cross-region dual-bucket replication. | CMEK. DR replica uses DR-region KMS key. | IAM bindings scoped to workload service account. |
| Azure Blob | GRS (geo-redundant storage) for critical data. Soft delete enabled (30-day retention). | CMK via Key Vault. DR replica encrypted with DR-region Key Vault key. | RBAC: workload managed identity only. |

### Database

| Resource | Backup mechanism | Encryption | Access control |
|---|---|---|---|
| RDS / Aurora | Automated backups (7-day retention). Manual cross-region snapshot copy for Tier 1. Aurora: automatic cross-region read replica for DR. | `storage_encrypted = true`, CMK. Snapshots inherit encryption. | Snapshot access restricted to DR recovery role. No public snapshot sharing. |
| Azure MSSQL | Automated backups with LTR (long-term retention) to 35 days. Geo-DR via active geo-replication for Tier 1. | TDE (Transparent Data Encryption) with CMK. | Backup access restricted to SQL admin role. |
| GCP Cloud SQL | Automated backups (7-day). Cross-region read replica for Tier 1. | CMEK. Backup inherits encryption. | IAM: backup access restricted to DR role. |

### Compute (EC2 / VMs)

| Resource | Backup mechanism | Encryption | Access control |
|---|---|---|---|
| EC2 instances | EBS snapshots (daily, 7-day retention). AMI baked in CI pipeline (golden image). | EBS snapshots encrypted with account-level default CMK. | Snapshot access restricted to DR role. AMI shared only within the account. |
| Azure VMs | Azure Backup with daily snapshots. | Azure Backup encrypts with platform-managed or CMK. | Recovery vault access restricted to DR role. |
| GCP VMs | Compute disk snapshots (daily). | Snapshot inherits CMEK from source disk. | IAM: snapshot access restricted to DR role. |

### Terraform state and infrastructure

| Asset | Backup mechanism |
|---|---|
| Terraform state (S3) | S3 versioning + cross-region replication. State is the single source of truth for infrastructure. |
| GitLab repository | GitLab Geo replication (if self-managed). GitHub mirror as backup. |
| OPA policies | Stored in a separate `policy-library` repo with its own backup. |
| CI/CD configuration | `.gitlab-ci.yml` is in the workload repo — backed up with the repo. |

## Cross-cloud failover: when is it realistic?

### Position: cross-cloud failover is NOT realistic for this programme

The programme's workloads are single-cloud. The COTS financial reconciliation tool runs on AWS. The Azure workloads are separate services. The GCP workloads are separate analytics pipelines. There is no cross-cloud application mesh (`../04-network-zero-trust/network-design.md` explicitly chose not to build one).

**Attempting cross-cloud failover would require:**

1. Data synchronisation between AWS RDS and Azure MSSQL / GCP Cloud SQL — a fundamentally different database technology with different replication protocols.
2. Cross-cloud networking with consistent latency and throughput — transit gateway / express route / cloud interconnect add 50–200ms latency, which is unacceptable for database transactions.
3. DNS-based traffic switching that accounts for data consistency — if the primary fails mid-transaction, the DR site may have stale data.
4. Application-level awareness of multi-cloud topology — the COTS tool's vendor does not support multi-cloud deployment.

**The cost and complexity of cross-cloud failover exceed the risk it mitigates.** For a 100-workload government programme, within-cloud DR (multi-AZ + cross-region) provides sufficient resilience at a fraction of the complexity.

### When cross-cloud failover IS appropriate

Cross-cloud failover makes sense for:
- Stateless web applications that can run identically on any cloud (not the case here — the COTS tool is AWS-specific).
- Organisations with thousands of workloads and dedicated multi-cloud platform teams (not the case here — ~100 workloads with a small platform team).
- Applications designed from day one for multi-cloud (not the case here — existing workloads are cloud-specific).

### The realistic DR approach

| Failure scenario | Recovery mechanism | RTO |
|---|---|---|
| Single AZ failure | Multi-AZ RDS failover + EC2 replacement in healthy AZ | < 5 minutes |
| Single AZ failure (compute only) | ALB health check + ASG replacement in healthy AZ | < 2 minutes |
| Full region failure | Restore from cross-region snapshot. Scale up DR VPC. Update DNS. | 2–4 hours |
| Account compromise / corruption | Restore from immutable backup (S3 object lock). Re-deploy from known-good Terraform state. | 4–8 hours |
| Ransomware / data corruption | Point-in-time recovery to pre-corruption timestamp. Restore from cross-region snapshot if local backups also affected. | 2–4 hours |

## What happens if an entire account/subscription/project needs to be rebuilt?

### What IS recoverable from Git

1. **All infrastructure** — Terraform state (backed up in S3 with cross-region replication) defines every resource. `terraform apply` in a new account recreates the infrastructure.
2. **All configuration** — IAM policies, security groups, network routing, encryption settings, backup policies — all defined in Terraform.
3. **Application code** — in GitLab, backed up.
4. **CI/CD pipeline** — `.gitlab-ci.yml` and shared component library are in Git.
5. **OPA policies** — in the `policy-library` repo.
6. **Container images** — if stored in ECR with image scanning, the latest known-good image can be identified and re-deployed. If images are in a public registry, they're trivially recoverable.

### What is NOT recoverable from Git

1. **Terraform state** — if the S3 backup is also lost (extremely unlikely with cross-region replication and object lock, but possible in a catastrophic scenario), the state must be reconstructed. This is painful but possible by running `terraform import` against the surviving cloud resources, or by rebuilding from scratch if the cloud resources are also lost.
2. **Database data** — the actual data in RDS is not in Git. It is in automated backups (7-day retention) and manual cross-region snapshots. If both are lost, data is unrecoverable. This is why cross-region snapshots are mandatory for Tier 1 workloads.
3. **Secrets** — if Secrets Manager / Key Vault data is lost, all credentials must be rotated. The passwords are not in Git (they shouldn't be — `CLD-007` fix).
4. **Access logs and audit trails** — CloudTrail logs, VPC flow logs, and Sentinel data are in the cloud provider's log storage. If the account is deleted, historical logs are lost unless exported to a separate account or external storage.
5. **DNS records** — if Route 53 / Azure DNS records are lost, they must be recreated manually. They are not in Terraform in the current terragoat structure (they should be — this is a gap to close).

### Recovery procedure (account-level rebuild)

| Step | Action | Time estimate |
|---|---|---|
| 1 | Create new AWS account (or new Azure subscription / GCP project) | 1–2 hours (automated via AWS Organizations) |
| 2 | Configure OIDC federation for CI/CD in the new account | 30 minutes |
| 3 | Restore Terraform state from cross-region S3 replica | 15 minutes |
| 4 | Update Terraform backend configuration to point to new account | 5 minutes |
| 5 | Run `terraform apply` to recreate all infrastructure | 30–60 minutes |
| 6 | Restore database from cross-region snapshot | 1–2 hours |
| 7 | Update DNS to point to new infrastructure | 15 minutes |
| 8 | Verify application functionality | 30 minutes |
| **Total** | | **~3–5 hours** |

This meets the 4-hour RTO for region-level failures, assuming cross-region snapshots exist.

## Cross-references

- Findings register (backup gaps): `../01-findings/findings-register.md` — `CLD-027` (weak backup retention)
- Network design (DR region connectivity): `../04-network-zero-trust/network-design.md`
- Data protection (encryption of backups): `../05-data-protection/encryption-key-mgmt.md`
- Architecture (HLD showing DR region): `../10-architecture/hld-diagram.md`
