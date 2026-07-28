# Severity methodology

This methodology is calibrated for the assessment scenario: a multi-cloud government programme with about 100 workloads, mostly AWS today, managed through Terraform and self-managed GitLab CI/CD, with Azure and GCP onboarding into the same governance model later this year. The rating is deliberately operational: it reflects what the programme must fix or compensate for before formal go-live sign-off, not a generic textbook score.

## Severity rubric

| Severity | Definition for this programme | Typical examples |
|---|---|---|
| **Critical** | Direct path to unauthenticated/public data exposure, internet-reachable database compromise, broad administrative privilege, hardcoded live-style credentials, or loss of detection on a high-value control plane. These require immediate remediation or formal compensating controls. | Public storage containing business data; public + unencrypted database; wildcard CI/service-account permissions on all resources; Kubernetes control plane reachable from the internet with weak authz; committed cloud keys. |
| **High** | Material control failure likely to support compromise, data loss, or non-compliance, but with a smaller blast radius, an additional access precondition, or a less direct exploitation path than Critical. | SSH/RDP open to the internet; encryption disabled on block storage; SQL injection/data exfiltration alerts disabled; unmanaged admin access; TLS not enforced for databases. |
| **Medium** | Security weakness that degrades hardening, auditability, resilience, or supply-chain integrity but is not usually a standalone compromise path. These should be remediated in the near-term hardening backlog. | Missing key rotation; mutable image tags; incomplete activity log categories; no CMEK where platform default encryption exists; unsupported runtimes requiring planned upgrade. |
| **Low** | Hygiene issue with limited immediate risk in isolation. Low findings still matter for policy consistency but do not displace exposure, identity, encryption, logging, or resilience risks. | Naming/documentation drift, minor hardening gaps, non-sensitive configuration inconsistencies. |

## Rating dimensions

Each finding is rated using four dimensions:

1. **Impact** — sensitivity of data or control plane affected, including whether the issue could expose citizen, financial, operational, or authentication data.
2. **Exploitability** — whether the issue is internet reachable, anonymous, usable by any cloud principal, or requires prior privileged access.
3. **Blast radius** — whether one workload, one account/subscription/project, or the whole landing-zone governance model is affected.
4. **Control failure depth** — whether multiple controls fail together, for example a public database that is also unencrypted and has backups disabled.

When several controls fail on one resource, the rating is elevated. `CLD-002` is Critical for that reason: the database is public, unencrypted, and has no backups, matching the programme audit trigger of a public and unencrypted database.

## Prioritisation framework layered on severity

The programme cannot remediate every issue at once across roughly 100 workloads, so the register includes both **severity** and **remediation priority**.

Prioritisation uses this sequence:

1. **Blast radius first** — fix issues that affect many workloads, accounts, subscriptions, projects, or reusable CI/CD identities before isolated workload hardening.
2. **Exploitability second** — internet-facing and anonymous access outrank issues requiring internal privileged access.
3. **Data protection third** — public data, unencrypted sensitive data, and weak key control outrank cosmetic hardening.
4. **Detection coverage fourth** — where remediation cannot be completed immediately, logging and alerting become the minimum acceptable compensating control.
5. **Remediation cost last** — quick, high-impact changes are pulled forward even if they are not the single highest severity finding.

## Remediation priority labels

| Priority | Meaning | Expected handling |
|---|---|---|
| **P0 — stop exposure** | Active or near-active exposure of data, credentials, or administrative control. | Fix immediately or isolate service. Open a risk exception only with named owner, expiry date, monitoring, and compensating controls. |
| **P1 — urgent control repair** | Serious control failure that materially increases compromise likelihood. | Fix in the current remediation wave or next approved change window. |
| **P2 — near-term hardening** | Important hardening or audit gap without a direct standalone compromise path. | Batch through platform backlog, reusable Terraform modules, and policy-as-code guardrails. |
| **P3 — scheduled hygiene** | Low-risk hygiene, documentation, or consistency issue. | Track through normal engineering backlog. |

## Effort estimates

| Estimate | Meaning |
|---|---|
| **S** | Terraform-only or small configuration change with low regression risk; typically less than two engineer-days including review. |
| **M** | Requires design validation, rotation, migration, workload testing, or coordination across teams; typically one sprint item. |
| **L** | Requires architecture change, product migration, downtime planning, or vendor coordination. |

## Treatment of constrained COTS workloads

The programme has a COTS financial reconciliation tool whose vendor driver cannot operate with storage encryption enabled before the compliance deadline. This does **not** downgrade encryption findings. Instead, the finding remains rated on inherent risk and the remediation plan must record compensating controls: private network placement, strict IAM, object-level access logging, detective alerts, short-lived credentials, contractual vendor remediation path, and a time-boxed risk acceptance.

## Tooling baseline assumed for later modules

The register is written so later modules can map controls into concrete tools without changing IDs:

- Terraform scanning: Checkov, tfsec/Trivy IaC, Terrascan, and OPA/Conftest policies in GitLab CI.
- Cloud posture validation: AWS Security Hub/Config/Access Analyzer, Microsoft Defender for Cloud/Azure Policy, and Google Security Command Center/Config Validator.
- Remediation target-state: `terraform-aws-modules`, Azure Verified Modules, Google Cloud Terraform modules, and AWS Landing Zone Accelerator-style central logging and guardrails.

## ID stability

Finding IDs use the `CLD-xxx` format and must not be renumbered. Later modules should reference these IDs directly, especially:

- `CLD-001` and `CLD-025` for the audit scenario's public storage bucket theme.
- `CLD-002` and `CLD-026` for the public database exposure theme.
- `CLD-003` and `CLD-010` for wildcard permission and CI/service-account governance.
- `CLD-016`, `CLD-024`, `CLD-028`, and `CLD-029` for centralised detection and alerting gaps.
