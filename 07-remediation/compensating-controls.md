# Module 8 — Compensating Controls for the COTS Financial Reconciliation Tool

## The constraint

The programme runs a COTS financial reconciliation tool whose vendor-imposed limitation prevents its connection driver from operating with storage encryption enabled. This tool cannot be re-platformed before the compliance deadline. The programme must go live with this limitation in place.

This does **not** mean encryption is optional. It means the programme must implement compensating controls that reduce the residual risk to an acceptable level, formally accept that residual risk, and track the exception to resolution.

## Compensating controls

### Control 1: Private network isolation (draws on Module 4)

**What it does:** The COTS workload's storage bucket and database are placed in the most restrictive network segment available. No public IP. No internet route. No VPC peering to non-production accounts. Access is restricted to the COTS application's specific subnet and the CI/CD identity for deployment only.

**Implementation (references Module 4 network tiers):**

- The storage bucket resides in the **data tier** — the most isolated network segment (`../04-network-zero-trust/network-design.md`). The data tier has no internet route at all.
- The bucket's VPC endpoint is a Gateway endpoint for S3, available only within the VPC. No public endpoint is created.
- Security groups / NACLs on the application subnet allow access to the storage bucket only from the COTS application's specific instance profile or service account. No other workload can reach it.
- Egress control: the COTS application's subnet has no NAT route to the internet. If the tool needs to reach an external API, that is routed through the centralised firewall with explicit allowlisting (`../04-network-zero-trust/network-design.md`, egress control section).

**Residual risk reduction:** Even without encryption at rest, the data is unreachable from the public internet, unreachable from other workloads, and unreachable from any network path that isn't explicitly allowlisted. An attacker would need to compromise the VPC itself or the specific COTS application host.

### Control 2: Object-level access logging and real-time alerting (draws on Module 5 and Module 6)

**What it does:** Every access to the unencrypted storage bucket is logged, and anomalous access triggers an immediate alert.

**Implementation:**

- **S3 server access logging** is enabled on the bucket, writing to a centralised logging bucket in the same account. This captures every API call: `GetObject`, `PutObject`, `DeleteObject`, `ListBucket`, and any administrative action.
- **CloudTrail data events** are enabled for the specific S3 bucket ARN. This provides an additional, independent log source with caller identity, source IP, and request parameters.
- **Sentinel / CloudWatch alarm** is configured on the CloudTrail data events log stream. Any access from a source IP outside the COTS application's subnet triggers a PagerDuty alert within 60 seconds. Any `DeleteObject` or `PutBucketPolicy` action triggers an immediate alert regardless of source IP (insider threat protection).
- **Access log retention:** 365 days minimum. Logs are stored in a bucket with object lock (WORM) enabled to prevent tampering.

**Residual risk reduction:** Even if data is accessed without encryption, the access is visible in real time. The SOC can detect and respond within minutes. The log chain is tamper-proof.

### Control 3: Strict IAM with resource conditions and session policies (draws on Module 3)

**What it does:** Only the COTS application's specific identity can access the unencrypted storage. No other identity — human or machine — can read or write to it without explicit, time-bound elevation.

**Implementation (references Module 3 IAM design):**

- The COTS application uses a dedicated IAM role (`cots-reconciliation-role`) with:
  - `s3:GetObject`, `s3:PutObject` scoped **only** to the specific bucket ARN: `arn:aws:s3:::cots-reconciliation-data/*`.
  - **No** `s3:DeleteObject`, `s3:PutBucketPolicy`, `s3:PutBucketAcl` — the application cannot delete data or modify bucket permissions.
  - A resource condition: `"s3:prefix": "reconciliation/"` — the application can only access objects under the `reconciliation/` prefix, not any other path in the bucket.
- **No human identity** has standing access to this bucket. Any human access (for support, auditing, or investigation) requires JIT elevation through the platform's PIM/elevation workflow (`../03-identity-governance/cross-cloud-iam-design.md`, JIT section), with approval, time limit, and full audit logging.
- **No cross-account access** is permitted. The bucket policy explicitly denies access from any principal outside the workload's AWS account.
- **Session policies** are attached to the COTS role at assume-role time, further restricting the effective permissions even if the underlying IAM policy is broader than intended.

**Residual risk reduction:** The blast radius of any compromise is limited to one bucket, one prefix, and one identity. The attacker cannot pivot to other resources, delete data, or modify the bucket's security posture.

### Control 4: Data classification tag and automated exception tracking (draws on Module 5)

**What it does:** The unencrypted bucket is automatically identified, tracked, and reported on as an exception.

**Implementation:**

- The bucket is tagged with `Classification: exception-cots` and `Encryption: vendor-constrained-no-at-rest`.
- An OPA policy in the CI pipeline (`../02-pipeline-supply-chain/pipeline-design.md`) flags any bucket with this tag as a known exception in scan reports — it does not fail the build, but it does annotate the MR with a reminder that the exception exists and its expiry date.
- A monthly compliance report (generated by a Lambda/Function that queries resource tags) lists all resources tagged as exceptions, their age, and their compensating controls. This report is reviewed by the platform security team and the programme's information security governance board.

## Residual risk rating

After all four compensating controls are in place:

| Dimension | Original risk (no encryption, public) | Residual risk (compensating controls) |
|---|---|---|
| **Data exposure** | Critical — anyone on the internet can read the data | **Low** — data is accessible only from one specific IAM role in one specific subnet, with no internet route |
| **Data deletion** | High — no backups, public access | **Low** — S3 versioning + object lock on logs + no delete permission on the application role |
| **Undetected access** | High — no logging or alerting | **Low** — real-time CloudTrail + S3 access log alerting, with 60-second detection SLA |
| **Persistence after incident** | High — no forensics capability | **Low** — immutable logs, access trail for investigation |

**Overall residual risk: Medium.** The encryption gap remains, but the exposure window is narrowed to a single identity on a private network with full visibility. This is an acceptable interim risk with a defined expiry.

## Risk acceptance

The residual risk must be formally accepted by a named role, not a named person (because personnel change):

- **Risk acceptor:** The programme's **Chief Information Security Officer (CISO)** or their delegated authority (e.g., Head of Platform Security).
- **Acceptance mechanism:** A signed risk acceptance form (or equivalent in the programme's GRC tool) documenting:
  - The specific asset (bucket ARN / resource ID)
  - The exception reason (vendor driver limitation)
  - The compensating controls in place
  - The residual risk rating (Medium)
  - The expiry date (see timeline below)
  - The next re-review date
- **The risk acceptance is time-bound.** It does not persist indefinitely.

## Time-bound remediation plan

| Phase | Timeframe | Action |
|---|---|---|
| **Interim (go-live)** | Compliance deadline | All four compensating controls in place. Risk acceptance signed. COTS tool operates without encryption at rest. |
| **Vendor engagement** | Months 1–3 | Formal vendor engagement: document the encryption requirement, request a timeline for driver update supporting encryption, and negotiate contractual commitment. |
| **Vendor update testing** | Months 3–6 | If vendor ships updated driver: test in non-production with encryption enabled. Validate all reconciliation functions work with encrypted storage. |
| **Production encryption** | Months 6–12 | Enable encryption at rest on the COTS workload's storage. Remove compensating controls that are no longer needed (network isolation and alerting remain as standard controls). Close the exception. |
| **If vendor does not deliver** | Month 12 | At the 12-month mark, the exception must be re-evaluated. Options: re-platform to a different tool (now in-scope), accept the risk with refreshed CISO sign-off and additional controls, or decommission the tool. The exception does not auto-renew. |

## Preventing exception proliferation

The hardest governance question: how do you stop this one exception from being used to justify similar exceptions across the ~100-workload estate?

### Concrete governance mechanism

**1. Formal exception register**

A central exception register (maintained in the programme's GRC tool or as a version-controlled Markdown file in this repo) records every active exception:

| ID | Resource | Exception reason | Compensating controls | Residual risk | Accepting role | Expiry date | Next review |
|---|---|---|---|---|---|---|---|
| EXC-001 | `arn:aws:s3:::cots-reconciliation-data` | COTS vendor driver cannot operate with encryption enabled | Private network isolation, access logging + alerting, strict IAM, object lock on logs | Medium | CISO | 2026-07-28 | 2026-10-28 |

**2. Exception approval process**

Any new exception request requires:

- Written justification with evidence that the standard control cannot be implemented.
- Proposed compensating controls reviewed by the platform security team.
- CISO sign-off (or delegate) with a mandatory expiry date.
- Registration in the exception register before go-live.

**3. Quarterly exception review**

Every exception is reviewed quarterly by the platform security team and the programme governance board. The review asks:

- Is the exception still justified?
- Has the vendor / product / situation changed?
- Are compensating controls still effective?
- Should the expiry date be extended, shortened, or the exception closed?

**4. Automated detection of new exceptions**

The OPA policy in the CI pipeline (`../02-pipeline-supply-chain/pipeline-design.md`) detects when any new resource is created without encryption and flags it. The pipeline does not auto-approve exceptions — it surfaces them for human review. A new exception without a registered exception ID in the register causes a pipeline failure.

**5. Exception budget**

The programme sets a hard limit: **no more than 3 active exceptions at any time** across the entire ~100-workload estate. If a new exception is requested and the budget is full, an existing exception must be closed first. This prevents gradual exception creep.

## Cross-references

- Network design (private isolation): `../04-network-zero-trust/network-design.md`
- Data protection (encryption default, classification tagging): `../05-data-protection/encryption-key-mgmt.md`
- Detection and IR (alerting on the exception bucket): `../06-detection-ir/monitoring-ir-plan.md`
- IAM governance (JIT elevation, no standing access): `../03-identity-governance/cross-cloud-iam-design.md`
- Pipeline (OPA exception detection): `../02-pipeline-supply-chain/pipeline-design.md`
- Compliance mapping (exception as documented deviation): `../09-compliance/compliance-mapping.md`
