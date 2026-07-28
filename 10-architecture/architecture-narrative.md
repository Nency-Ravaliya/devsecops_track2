# Architecture Narrative

## HLD — High-Level Architecture

### What the diagram shows

The high-level diagram (`hld-diagram.md`) presents the target-state secure architecture as a system-context view. It shows:

1. **Development Zone** — GitLab source control and CI/CD runners, connected to the identity boundary via OIDC federation and to the governance layer via policy-as-code scanning.
2. **Identity Boundary** — Entra ID as the central IdP, federated into all three clouds via SSO/JIT/PIM.
3. **Secrets & Key Management** — Per-cloud native KMS (AWS KMS, Azure Key Vault, GCP Cloud KMS) for encryption key management, plus HashiCorp Vault for application secrets.
4. **Public Edge Tier** — CDN, WAF, and load balancers as the only internet-facing components. TLS termination happens here. No application logic runs in the edge tier.
5. **Three Cloud Landing Zones** — AWS, Azure, and GCP, each with a hub/shared-services VPC/VNet, an application tier (no public IPs), and a data tier (private endpoints only).
6. **Centralised Detection** — Microsoft Sentinel as the single SIEM aggregating logs from all three clouds, with PagerDuty for alerting and a security posture dashboard.
7. **Governance Layer** — OPA/Conftest for policy-as-code, Checkov/Trivy for IaC scanning, and Dependency-Track for SBOM tracking.

### Key security decisions reflected in the diagram

1. **No workload talks directly to the internet.** All ingress goes through the edge tier (CDN/WAF/LB). All egress goes through centralised NAT/firewall. This was a direct response to `CLD-013`, `CLD-014`, `CLD-015` (open SSH/RDP/firewall to the internet).

2. **Identity is centralised, not per-cloud.** Entra ID is the single IdP for all human access. CI/CD uses OIDC federation to each cloud (Module 3). This eliminates the wildcard IAM user problem (`CLD-003`) and removes static credentials (`CLD-004`–`CLD-008`).

3. **Encryption is per-cloud, governed centrally.** Each cloud uses its native KMS for envelope encryption (operational simplicity, native integration), but OPA policies in the CI pipeline enforce the same encryption requirements across all providers (governance consistency).

4. **Detection is centralised, not per-cloud.** All logs from all three clouds flow into Sentinel. This directly addresses the "no centralised detection" audit trigger and `CLD-028`/`CLD-029`.

5. **Cross-cloud links are for governance only.** There is no cross-cloud runtime traffic. Workloads run in one cloud. Cross-cloud connectivity exists only for SIEM ingestion, identity federation, and CI/CD artifact sync. This avoids the complexity and attack surface of a multi-cloud application mesh.

### Rejected alternative: single-cloud consolidation

**Alternative considered:** Migrate everything to AWS (or Azure) and eliminate multi-cloud complexity entirely.

**Why rejected:** The programme already has workloads on AWS, Azure, and GCP. Azure and GCP are being onboarded, not eliminated. The programme's governance model must work across all three clouds because the workloads exist on all three. Consolidating to a single cloud would require re-platforming existing workloads (including the COTS tool) at a cost and timeline incompatible with the compliance deadline. The chosen architecture makes multi-cloud workable without pretending it's simple.

### Rejected alternative: active-active multi-cloud

**Alternative considered:** Run identical workloads on all three clouds simultaneously for availability.

**Why rejected:** Active-active multi-cloud adds enormous operational complexity (data synchronisation, split-brain handling, cross-cloud networking) for a marginal availability improvement. The programme's resilience requirements (Module 11) are better served by within-cloud HA (multi-AZ) and within-cloud DR (cross-region backup and failover) than by cross-cloud active-active. Cross-cloud active-active is a valid architecture for hyperscale SaaS companies; it is overkill for a government programme with ~100 workloads.

---

## LLD — Low-Level Architecture

### Scope of the LLD

The LLD expands one representative slice of the HLD: **the path from GitLab CI/CD through to a production RDS database in AWS**, including the identity, network, encryption, and detection components that protect it. This slice was chosen because it directly touches the three most critical Module 1 findings (`CLD-002`, `CLD-003`, `CLD-007`) and therefore demonstrates how the target state resolves the audit trigger.

### LLD diagram

See `lld-diagram.md` for the Mermaid diagram.

### Resource-level detail

| Component | AWS Resource | Identity | Network | Encryption |
|---|---|---|---|---|
| **GitLab CI runner** | GitLab SaaS or self-managed runner | OIDC token issued per pipeline job | Outbound only to AWS STS + S3 + ECR | Pipeline artifacts encrypted at rest in GitLab |
| **CI identity** | `ci-deploy-workload` IAM role | OIDC federation from GitLab (Module 3) | No network access — API-only via STS | N/A |
| **Terraform state** | S3 bucket `workload-tfstate` + DynamoDB lock table | CI role: `s3:GetObject/PutObject` + DynamoDB | Private bucket, no public access | SSE-KMS with CMK, bucket versioning |
| **Application EC2** | `aws_instance.db_app` in private subnet | Instance profile: scoped workload role (Module 3) | Private subnet, no public IP, SSM for admin | EBS encrypted with CMK (`CLD-018` fix) |
| **Application LB** | `aws_lb` (ALB, not Classic) | N/A (no IAM) | Public subnet, HTTPS listener only (ACM cert) | TLS 1.3 termination at LB |
| **RDS database** | `aws_db_instance` in private subnet | DB credentials in Secrets Manager | Private subnet only, SG allows 3306 from app subnet only | `storage_encrypted = true`, CMK, `rds.force_ssl = 1` |
| **Secrets** | AWS Secrets Manager | CI role and app instance profile can read | Private endpoint only | Encrypted with dedicated Secrets Manager CMK |
| **Logging** | CloudWatch Logs → S3 (central log bucket) | Read-only role for SOC | VPC flow logs + RDS audit logs | Log bucket encrypted with CMK, object lock |
| **Detection** | GuardDuty + Sentinel | N/A (service-level) | API-level (CloudTrail) | N/A |
| **Policy enforcement** | OPA/Conftest in CI pipeline | CI role | N/A | N/A |

### Port and protocol detail

| Path | Source | Destination | Port | Protocol | Encryption | Justification |
|---|---|---|---|---|---|---|
| User → LB | Internet | ALB | 443 | TCP/TLS 1.3 | ACM certificate | HTTPS only, TLS 1.3 enforced |
| LB → EC2 | ALB security group | EC2 security group | 80 | TCP | Re-encrypted via mTLS (Istio) or plaintext within VPC | Internal traffic within trusted VPC |
| EC2 → RDS | EC2 security group | RDS security group | 3306 | TCP/TLS | `rds.force_ssl = 1` | MySQL with forced TLS |
| EC2 → Secrets Manager | EC2 security group | AWS service | 443 | TCP/TLS | AWS service endpoint encryption | Retrieve DB password at runtime |
| EC2 → SSM | EC2 (outbound) | AWS SSM service | 443 | TCP/TLS | HTTPS | Admin access without SSH |
| VPC → CloudWatch | VPC flow log | CloudWatch Logs | 443 | TCP/TLS | AWS service encryption | Log shipping |
| VPC → GuardDuty | VPC (API calls) | GuardDuty | N/A | API | TLS | Threat detection |

### How the Module 2 pipeline and Module 6 detection physically sit

**Module 2 pipeline:** Runs on GitLab runners (self-managed or SaaS). The runners authenticate to AWS via OIDC federation (Module 3) and execute Checkov, Trivy, OPA, and Gitleaks as job steps. The pipeline has no runtime access to the production VPC — it communicates only through the AWS STS API (for role assumption) and S3 API (for state management). The pipeline is in the "Development Zone" of the HLD.

**Module 6 detection:** GuardDuty monitors CloudTrail events and VPC flow logs within the AWS account. Sentinel connects to AWS via the AMA (Azure Monitor Agent) or EventBridge integration and ingests CloudTrail, GuardDuty findings, and VPC flow logs. The SOC monitors Sentinel dashboards and receives PagerDuty alerts for Critical/High findings. Detection operates at the API level (CloudTrail) and network level (flow logs) — it does not sit inline in the traffic path.

### Key LLD decisions

1. **ALB replaces Classic ELB.** The Classic ELB in terragoat (`CLD-015`) only supports HTTP. Application Load Balancer supports HTTPS natively with ACM certificates, WAF integration, and modern TLS policies.

2. **Secrets Manager replaces committed passwords.** The database password is no longer a Terraform variable (`CLD-007`) or embedded in user_data (`CLD-008`). The application retrieves it from Secrets Manager at startup using its instance profile.

3. **SSM replaces SSH.** The Classic ELB SSH open to the internet (`CLD-013`) is replaced by SSM Session Manager, which requires no inbound port 22, no bastion host, and no SSH keys. Admin access goes through the AWS console or CLI with the engineer's Entra ID credentials.

4. **Multi-AZ for availability.** The RDS instance runs in Multi-AZ mode. The application runs in at least two AZs behind the ALB. This provides availability without needing cross-cloud failover.

### Rejected LLD alternative: direct VPC peering between environments

**Alternative considered:** Peer the application VPC directly with the data VPC for lower latency.

**Why rejected:** VPC peering creates a flat network where both VPCs can route to each other. If the application VPC is compromised (e.g., through the web application), the attacker can reach the data VPC directly. Transit Gateway with explicit route tables provides the same connectivity with routing controls that can be audited and restricted. The slight latency increase ( Transit Gateway adds ~1-3ms) is negligible for database queries.

## Cross-references

- HLD diagram: `hld-diagram.md`
- LLD diagram: `lld-diagram.md`
- Network design: `../04-network-zero-trust/network-design.md`
- Identity governance: `../03-identity-governance/cross-cloud-iam-design.md`
- Data protection: `../05-data-protection/encryption-key-mgmt.md`
- Pipeline: `../02-pipeline-supply-chain/pipeline-design.md`
- Detection: `../06-detection-ir/monitoring-ir-plan.md`
- Findings register: `../01-findings/findings-register.md`
