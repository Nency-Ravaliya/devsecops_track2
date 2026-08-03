# Module 2 — Shift-Left Pipeline & Software Supply Chain Security

## Context and purpose

This module designs a CI/CD pipeline for the programme's self-managed GitLab CI/CD estate that would have caught the audit trigger findings before they reached production. The programme currently runs roughly 100 workloads, mostly on AWS via Terraform, with Azure and GCP onboarding planned for later this year. The pipeline must scale across all of those workloads without creating a human review bottleneck, while also treating the software supply chain — dependencies, container images, build provenance — as in scope alongside the Terraform.

The findings register in `../01-findings/findings-register.md` defines the universe of issues. This pipeline design references those `CLD-xxx` IDs where a gate would have caught a specific misconfiguration.

## Pipeline stages

The pipeline has seven stages, executed in order. Each stage contains one or more security tools. Some gates hard-fail the pipeline; others soft-fail (warn and annotate the merge request) depending on the risk class.

```
┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐   ┌───────────┐   ┌─────────────┐   ┌──────────┐
│ Preflight│──▶│ Secrets Scan │──▶│ IaC Scan │──▶│ SCA / SBOM   │──▶│ Container │──▶│ Approval    │──▶│ Deploy   │
│ (lint)   │   │              │   │          │   │              │   │ Scan      │   │ Gate        │   │          │
└──────────┘   └──────────────┘   └──────────┘   └──────────────┘   └───────────┘   └─────────────┘   └──────────┘
```

### Stage 1 — Preflight / lint

**Purpose:** Catch syntactically broken Terraform, malformed YAML, and basic structural issues before burning scanner cycles.

| Tool | What it checks | Gate behaviour |
|---|---|---|
| `terraform fmt -check -recursive` | HCL formatting drift | Soft-fail (warn); enforced via MR policy, not blocking production. |
| `terraform validate` | Module and provider schema errors | Hard-fail on errors. |
| `yamllint` | YAML files including GitLab CI configs | Soft-fail (warn). |

### Stage 2 — Secret detection

**Purpose:** Prevent committed credentials, tokens, and keys from reaching the default branch. Would have caught `CLD-004` (hardcoded provider keys), `CLD-005` (EC2 user data keys), `CLD-006` (Lambda env var keys), `CLD-007` (database password in variable default), `CLD-008` (database password in user data), and `CLD-025` (Azure SQL/MSSQL hardcoded passwords).

| Tool | What it checks | Gate behaviour |
|---|---|---|
| **Gitleaks v8** (primary) | Regex and entropy-based secret patterns across all tracked files and diffs. Uses built-in rules plus a `.gitleaks.toml` with organisation-specific patterns for AWS access keys, Azure tenant secrets, GCP service account JSON structure, and Terraform `sensitive` variable leaks. | **Hard-fail** on any match. Pipeline stops. No secret committed to the default branch should survive this gate. |
| **GitLab Secret Detection** (built-in) | GitLab's own embedded secret scanner running as a second layer. Free for self-managed Ultimate/Premium, uses SAST analyser. | Hard-fail as a redundant check. Two independent detectors reduce false-negative risk. |

**Allowlisting:** Terragoat contains intentional demo secrets. A project-level `.gitleaks.toml` allowlist file is maintained per-repo. Allowlist entries require a comment citing the justification and a link to the finding ID or training-repo exception, and allowlists are subject to quarterly review through the platform team.

### Stage 3 — IaC security scanning

**Purpose:** Catch the storage, database, IAM, networking, encryption, and logging misconfigurations that constitute the bulk of the Module 1 register. This is the primary shift-left gate.

| Tool | What it checks | Gate behaviour |
|---|---|---|
| **Checkov v3** (primary) | Multi-cloud Terraform, CloudFormation, Kubernetes manifests, Helm, Dockerfile, and serverless. Checkov already has built-in checks for every CLD finding class: S3 public access (CKV_AWS_19/20/21 → `CLD-001`), RDS public+unencrypted (CKV_AWS_16/17 → `CLD-002`), IAM wildcard (CKV_AWS_1/62 → `CLD-003`), provider credentials (CKV_AWS_41 → `CLD-004`), EBS encryption (CKV_AWS_3 → `CLD-018`), security group SSH (CKV_AWS_24 → `CLD-013`), Azure NSG (CKV_AZURE_9/10 → `CLD-014`), GCP firewall (CKV_GCP_2/3 → `CLD-015`), and dozens more. Runs as `checkov -d . --framework terraform --compact --output cli --output junitxml --output sarif`. | **Hard-fail on Critical + High** — any check mapped to a P0 or P1 finding class blocks the pipeline. Medium and Low are soft-fail and appear as MR annotations. |
| **Trivy IaC** (secondary) | Covers the same frameworks with a different rule engine, reducing false negatives. Runs as `trivy config --severity CRITICAL,HIGH --exit-code 1 .`. | **Hard-fail on Critical + High** from a different rule base. Medium and Low are informational. |
| **OPA / Conftest** (custom policy) | Organisation-specific policies that go beyond vendor defaults: enforce tagging standards, mandate KMS key ARN for encryption resources, enforce backup retention minimums, and block known-bad patterns like `force_destroy = true` on production buckets. Policies are maintained in a central `policy-library/` repo and included as a GitLab CI component. | **Hard-fail on violations.** Custom policies directly encode programme governance decisions. |

**Why two commercial-grade scanners plus OPA:** Checkov and Trivy IaC overlap substantially but each catches edge cases the other misses. OPA adds organisation-specific logic that generic rules cannot express. Running all three in parallel adds under 90 seconds to pipeline time and materially reduces false-negative risk across multi-cloud.

### Stage 4 — Dependency / SCA scanning and SBOM generation

**Purpose:** Catch vulnerable transitive dependencies and generate an SBOM for provenance tracking. Applies to application code, Lambda packages, Dockerfiles, and support scripts, not just Terraform.

| Tool | What it checks | Gate behaviour |
|---|---|---|
| **Trivy SCA** (`trivy fs --scanners vuln --severity CRITICAL,HIGH`) | CVE scanning of `package-lock.json`, `requirements.txt`, `pom.xml`, Go modules, Gemfiles, and lockfiles. | **Hard-fail on Critical CVEs** with a confirmed exploit path (EPSS > 0.5 or CISA KEV listed). High CVEs are soft-fail with a 14-day SLA for remediation. |
| **Syft v1** | Generates CycloneDX SBOM from the repository and any built container images. Output stored as a pipeline artifact and pushed to a central SBOM registry (a GitLab generic package registry or Dependency-Track instance). | No gate (generation only). |
| **Grype** (optional validation) | Validates the SBOM against the NVD/OSV database as a cross-check against Trivy findings. | Soft-fail. |

SBOM outputs feed into Dependency-Track or a lightweight tracking sheet to maintain a running inventory of dependencies across the programme's 100+ workloads. When a new CVE is published, the platform team can query which workloads are affected without re-scanning every repo.

### Stage 5 — Container image scanning

**Purpose:** Catch vulnerabilities, misconfigurations, and unsigned images before deployment.

| Tool | What it checks | Gate behaviour |
|---|---|---|
| **Trivy image** (`trivy image --severity CRITICAL,HIGH`) | OS package CVEs, embedded secrets, Dockerfile best practices. | **Hard-fail on Critical CVEs** in the OS layer or application layer. High CVEs are soft-fail with SLA. |
| **Cosign / Sigstore** | Verifies image signatures against the CI signing key. If the image was not built and signed by this pipeline, it does not deploy. | **Hard-fail if signature validation fails.** Catches supply-chain tampering. This gate also supports `CLD-030` by enforcing immutable, signed image deployment rather than trusting mutable tags. |

### Stage 6 — Protected environment approval gate

**Purpose:** Production deployments require explicit security and operations sign-off. This is a human gate, not an automated scanner.

**How it works:**

- GitLab Protected Environments are configured for `production` and `staging`. The `production` environment requires approval from at least one member of the `@security-reviewers` group before the deploy job can run.
- The approval request includes a summary of all scan results from stages 2–5, automatically assembled from pipeline artifacts.
- The approval workflow is tiered by workload criticality (see "Scaling" section below).
- This gate does not apply to lower environments (dev, sandbox), which deploy automatically after passing the automated gates.

### Stage 7 — Deploy

**Purpose:** Apply Terraform changes through a controlled plan-and-apply workflow.

- `terraform plan -out=tfplan` runs first and the plan is stored as a pipeline artifact.
- The plan is diffed against the expected baseline and any new resource creation in restricted resource types (IAM roles, public endpoints, security groups) triggers an additional annotation.
- `terraform apply tfplan` runs only after the approval gate (for production) or after passing automated gates (for lower environments).
- Post-apply, a `terraform show -json tfplan | checkov` validation re-confirms the applied state matches the scanned intent.

## Hard-fail vs soft-fail reasoning

| Gate class | Behaviour | Rationale |
|---|---|---|
| Committed secrets | Hard-fail | No remediation path after merge — secrets in Git history require rotation, not just deletion. The cost of a false negative is credential rotation across the estate. |
| IaC Critical/High | Hard-fail | These map to the audit trigger findings. Letting them merge means re-creating the incident the programme exists to fix. |
| IaC Medium/Low | Soft-fail (MR annotation) | Important for posture but blocking on every Medium finding across 100 workloads would make the pipeline unusable. Tracked through SLA and periodic sweep. |
| Dependency Critical CVE (CISA KEV / high EPSS) | Hard-fail | Actively exploited vulnerabilities should never ship knowingly. |
| Dependency High CVE | Soft-fail with 14-day SLA | Not all High CVEs are exploitable in the workload context. Teams get time to assess and remediate. |
| Container Critical CVE | Hard-fail | Same reasoning as dependency. |
| Image signature validation | Hard-fail | Unsigned images break the chain of trust entirely. |
| Custom OPA policy | Hard-fail | These encode programme-specific governance decisions; violating them is a policy breach, not a suggestion. |

## Scaling across ~100 workloads

The programme cannot afford a security engineer reviewing every merge request for every workload. The pipeline scales through three mechanisms:

### 1. Workload criticality tiers

Every workload is classified into one of three tiers, recorded as a GitLab CI variable (`WORKLOAD_TIER`) set in the project's CI/CD settings:

| Tier | Criteria | Pipeline treatment |
|---|---|---|
| **Tier 1 — Critical** | Handles citizen data, financial data, authentication, or is internet-facing. Roughly 15–20 workloads. | Full scanner suite. Human approval gate for production. IaC findings at Medium and above hard-fail. |
| **Tier 2 — Standard** | Internal business workloads with moderate data sensitivity. Roughly 50–60 workloads. | Full scanner suite. Human approval only for infrastructure changes touching IAM, networking, or encryption resources. Medium findings are soft-fail. |
| **Tier 3 — Low risk** | Internal tools, sandboxes, dev/test environments. Roughly 20–30 workloads. | Secrets and Critical/High IaC checks only. No human approval gate. Medium and Low findings are informational only. |

This classification is maintained in a central YAML file (`workload-tiers.yml`) referenced by the shared CI/CD component library and updated quarterly by the platform security team.

### 2. Shared CI/CD component library

Rather than maintaining a `.gitlab-ci.yml` template in each of 100 repositories, the programme publishes a set of **GitLab CI/CD components** (using GitLab's `include:component` mechanism) from a central `ci-security-components` repository. Individual workload repos include a single line:

```yaml
include:
  - component: $CI_SERVER_FQDN/platform/ci-security-components/devsecops-pipeline@v2.1
    inputs:
      workload_tier: "tier-1"
      cloud_providers: ["aws"]
```

When a new scanner is added, a policy is updated, or a threshold is changed, it happens once in the component library and propagates to all consuming pipelines on their next run.

### 3. Risk-based sampling for retroactive sweeps

Not every workload can be reviewed in detail during the remediation wave. The platform team runs a scheduled pipeline (`on: schedule`) against all Terraform repositories weekly that:

- Runs Checkov and Trivy IaC in report-only (soft-fail) mode.
- Aggregates results into a central findings dashboard (GitLab Security Dashboard or a custom report pushed to the SIEM).
- Flags workloads that have regressed or newly match a Critical/High pattern.

This scheduled sweep catches drift, ensures coverage even for workloads that deploy infrequently, and gives the security team a prioritised backlog of issues to sequence through remediation waves.

## SBOM and dependency provenance

- Every pipeline run that includes application code or container builds generates a CycloneDX SBOM using Syft.
- SBOMs are stored as GitLab pipeline artifacts with a 90-day retention.
- SBOMs are additionally pushed to a central **Dependency-Track** instance (self-hosted, backed by PostgreSQL), which provides:
  - Continuous monitoring against the NVD, GitHub Advisory Database, and OSV.
  - Portfolio-level visibility into which of the 100 workloads are affected by a newly published CVE.
  - Automated issue creation in the workload's GitLab project when a Critical dependency vulnerability is published.
- Container images are signed with **Cosign** (keyless or KMS-backed signing key) at build time, and signatures are verified at deploy time and by admission controllers in Kubernetes clusters.
- The programme should publish a minimum dependency policy: no dependency older than its last CVE fix, no dependency with known CISA KEV entries unpatched beyond 48 hours for Critical, 14 days for High.

## Multi-cloud onboarding: what changes for Azure and GCP

The pipeline design is already multi-cloud aware because Checkov, Trivy IaC, and OPA/Conftest all support AWS, Azure, and GCP Terraform providers natively. When Azure and GCP workloads are formally onboarded:

| Concern | What changes | What stays the same |
|---|---|---|
| **IaC scanning** | No change needed. Checkov/Trivy already scan `azurerm_*` and `google_*` resources. The OPA policy library needs Azure- and GCP-specific custom policies (e.g., enforce Azure Disk Encryption, enforce GCP Public Access Prevention on buckets). | Core pipeline stages, gate logic, and artifact structure. |
| **Secrets detection** | Add GCP service account JSON key patterns and Azure client secret patterns to `.gitleaks.toml`. GitLab Secret Detection already covers these. | Gitleaks and GitLab Secret Detection. |
| **Provider authentication** | Add OIDC federation for Azure (GitLab → Azure Workload Identity Federation) and GCP (GitLab → GCP Workload Identity Federation) alongside the existing AWS STS assume-role pattern. Remove any static credentials. | The OIDC pattern is the same across clouds; only the token exchange endpoint changes. |
| **Terraform state** | Azure workloads use Azure Storage backend; GCP workloads use GCS backend. State access must be scoped to the CI identity for that workload only. | State encryption and access control requirements are the same. |
| **Approval gates** | The `WORKLOAD_TIER` classification applies regardless of cloud. Tier 1 Azure/GCP workloads still require human approval for production. | Protected environment mechanism. |
| **OPA custom policies** | Write provider-specific Rego policies for Azure NSG rules, GCP firewall rules, Azure Disk Encryption, GCP Public Access Prevention, and Azure Defender settings. | OPA/Conftest infrastructure and pipeline integration. |
| **Container scanning** | No change if containers are built in the same pipeline. If Azure Container Registry or GCP Artifact Registry replaces/supplements ECR, add Cosign verification against the registry-specific signing configuration. | Trivy image, Cosign chain of trust. |

The key governance decision is: **one component library, one security policy surface, multiple cloud targets.** Adding a provider should be a configuration change in the component inputs, not a pipeline redesign.

## How each audit trigger finding would have been caught

| Audit trigger item | Module 1 finding(s) | Pipeline gate that catches it |
|---|---|---|
| Two storage buckets with public access disabled | `CLD-001`, `CLD-011` | IaC scan — Checkov CKV_AWS_19/20/21 (S3), CKV_GCP_28 (GCS) hard-fail on Critical |
| Database with encryption disabled and public access | `CLD-002`, `CLD-012` | IaC scan — Checkov CKV_AWS_16/17 (RDS), CKV_GCP_6 (Cloud SQL) hard-fail on Critical |
| IAM policy with wildcard permissions on CI account | `CLD-003`, `CLD-009`, `CLD-010` | IaC scan — Checkov CKV_AWS_1/62 (IAM wildcard), CKV_AZURE_39 (role def), OPA custom policy hard-fail |
| Inconsistent audit logging | `CLD-016`, `CLD-017`, `CLD-028`, `CLD-029` | IaC scan — Checkov CKV_GCP_1 (GKE logging), CKV_AZURE_4 (AKS monitoring), OPA policy for mandatory logging resources |
| No centralised detection or alerting | `CLD-024`, `CLD-029` | IaC scan — Checkov CKV_AZURE_26 (Defender pricing), OPA policy requiring alert routing |

## Cross-references

- Findings register: `../01-findings/findings-register.md`
- Severity methodology: `../01-findings/severity-methodology.md`
- Identity governance (CI/CD identity model): `../03-identity-governance/cross-cloud-iam-design.md`
- Remediation advisory (implementation sequencing): `../07-remediation/remediation-advisory.md`
- Compensating controls (COTS handling): `../07-remediation/compensating-controls.md`
