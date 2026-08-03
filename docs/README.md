# DevSecOps Assessment — Track 2

## Executive summary

A hands-on review of the cloned terragoat reference target identified **30 findings** (13 Critical, 13 High, 4 Medium) across AWS, Azure, and GCP Terraform configurations. The findings directly map to the programme's audit trigger: public storage buckets (`CLD-001`, `CLD-011`), a public and unencrypted database (`CLD-002`, `CLD-012`), wildcard IAM permissions on a CI service account (`CLD-003`, `CLD-009`, `CLD-010`), inconsistent logging (`CLD-028`, `CLD-029`), and no centralised detection or alerting.

The programme can remediate all Critical and High findings within the quarter using Terraform-native fixes and a shared CI/CD component library. One COTS exception — a financial reconciliation tool whose vendor driver cannot operate with storage encryption — requires formal compensating controls (private network isolation, real-time access alerting, strict IAM, and a 12-month time-bound exception with CISO acceptance).

The target-state architecture centralises identity through Entra ID and OIDC federation, segments workloads into three network tiers (edge / application / data), enforces encryption at rest with per-cloud KMS governed by a single OPA policy framework, and detects threats through a centralised SIEM (Microsoft Sentinel) aggregating logs from all three clouds.

## Reference repository choice

The selected reference target is **terragoat** (`https://github.com/bridgecrewio/terragoat`), cloned into `reference-target/` because it was the most operationally useful starting point for this assessment. Cfngoat is useful for Azure-specific misconfiguration review, but this programme is multi-cloud with AWS as the dominant estate today, so a repo that already demonstrates AWS/Azure/GCP Terraform patterns was more relevant. The Landing Zone Accelerator repo is valuable as an architectural target-state baseline, not as an intentionally misconfigured review corpus, so it fits later architecture and remediation work rather than initial assessment. The `terraform-aws-modules` ecosystem is the right hardened standard for remediation modules and long-term service composition, but it is not a complete runnable training estate. Terragoat gave a realistic, multi-cloud Terraform base that could be reviewed quickly while still leaving enough room to map findings back to AWS, Azure and GCP controls.

## Reference target note

`reference-target/` was **cloned** from GitHub for local review. It was not forked in this environment because there is no authenticated GitHub CLI session configured here. To fork it properly on GitHub:

1. Open `https://github.com/bridgecrewio/terragoat`.
2. Click **Fork**.
3. Choose the target GitHub organisation or personal account.
4. Clone the fork into `reference-target/` instead of the upstream repo if you want the submission repo to carry your own fork history.

The cloned terragoat repository intentionally contains demo misconfigurations and placeholder credentials for training purposes. A manual and automated scan of `reference-target/` confirmed that the repository does **not** contain live cloud secrets, tokens, internal infrastructure values, or customer data. Reviewers should still treat its contents as intentionally insecure sample infrastructure, not as a clean baseline.

## How this repo is organised

| Module | Path | Purpose |
|---|---|---|
| Module 1 — Findings | `01-findings/findings-register.md`, `01-findings/severity-methodology.md` | Audit findings, IDs, severity model and prioritisation notes |
| Module 2 — Pipeline and supply chain | `02-pipeline-supply-chain/pipeline-design.md`, `02-pipeline-supply-chain/.gitlab-ci-example.yml` | CI/CD design, shift-left controls, SCA/SAST/IaC scanning, artifact integrity |
| Module 3 — Identity governance | `03-identity-governance/cross-cloud-iam-design.md` | Cross-cloud identity model, CI/CD identity, least-privilege governance |
| Module 4 — Network and zero trust | `04-network-zero-trust/network-design.md` | Network segmentation, private connectivity, zero-trust controls |
| Module 5 — Data protection | `05-data-protection/encryption-key-mgmt.md` | Encryption at rest/in transit, key management, storage protection |
| Module 6 — Detection and incident response | `06-detection-ir/monitoring-ir-plan.md` | Centralised logging, detection, alerting and IR workflow |
| Module 7 — Remediation | `07-remediation/remediation-advisory.md`, `07-remediation/compensating-controls.md`, `07-remediation/fixed-terraform/` | Remediation guidance, compensating controls for COTS limitations, hardened Terraform examples |
| Module 8 — Threat model | `08-threat-model/threat-model.md` | Threat scenarios, attack paths and risk narrative |
| Module 9 — Compliance mapping | `09-compliance/compliance-mapping.md` | Control mapping across frameworks and audit artefacts |
| Module 10 — Architecture | `10-architecture/hld-diagram.md`, `10-architecture/lld-diagram.md`, `10-architecture/architecture-narrative.md` | Architecture narrative and diagram placeholders for HLD/LLD |
| Module 11 — Resilience and DR | `11-resilience-dr/dr-plan.md` | Resilience assumptions, backup strategy, failover and DR plan |
| Module 12 — Presentation | `12-presentation/slides.pdf` | Presentation deck placeholder |
| Reference target | `reference-target/` | Cloned terragoat repository used as the assessment review target |

Modules 1 through 13 map to the assessment prompt sequence. This README currently references the first 12 content modules plus the reference target; the final presentation/QA prompt will be captured through the deck and supporting artefacts rather than a separate numbered folder.

## Status

- Folder scaffold created
- Reference target cloned
- Secret scan completed on reference target
- All 13 modules written and committed
- Presentation deck rendered to PDF
- Consistency review complete: CLD-xxx IDs referenced consistently across all modules, no secrets found outside reference-target, all required files present and non-empty
