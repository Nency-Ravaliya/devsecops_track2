# Module 6 — Detection, Monitoring & Incident Response

## Context

The audit trigger explicitly states: "no centralised detection or alerting on any of it." `CLD-028` documents disabled network flow logs and incomplete activity logs. `CLD-029` documents Azure Defender on Free tier with notifications off. `CLD-024` documents SQL injection and data exfiltration alerts deliberately disabled. `CLD-016` and `CLD-017` document Kubernetes logging/monitoring off on both GKE and AKS.

This module designs a detection and monitoring capability that would have caught the audit findings before they became an escalation event, and describes how the programme handles the confirmed-wildcard-CI-account-compromise scenario end to end.

## CSPM approach: continuous configuration monitoring

### Tooling per cloud

| Cloud | Primary CSPM | What it monitors | How findings feed the backlog |
|---|---|---|---|
| **AWS** | AWS Security Hub + AWS Config | Config rules for encryption defaults, public access, IAM policies, security groups, logging. Security Hub aggregates findings from GuardDuty, Inspector, Macie, and Config into a single severity-scored dashboard. | Security Hub findings are exported via EventBridge to an SNS topic → GitLab issue creation (one issue per Critical/High finding). Config non-compliant resources are tagged and tracked. |
| **Azure** | Microsoft Defender for Cloud (Standard tier) | Defender plans for Servers, SQL, Storage, Containers, Key Vault, App Service. Azure Policy for compliance state. | Defender recommendations export to Azure Sentinel or a Log Analytics workspace → same GitLab issue creation pipeline. Azure Policy compliance dashboard shows remediation progress. |
| **GCP** | Google Security Command Center Premium + Cloud Config Validator | SCC findings for public access, IAM misconfig, network exposure. Config Validator runs OPA policies against GCP resource graph. | SCC findings export via Pub/Sub → same GitLab issue creation pipeline. Config Validator violations are tracked in a central compliance report. |

### Cross-cloud aggregation

All three CSPM tools feed into a **single SIEM** — Microsoft Sentinel (chosen because the programme already uses Entra ID as the IdP, and Sentinel integrates natively with Azure AD audit logs, AWS CloudTrail via AMA agent, and GCP logs via Pub/Sub connector).

| Log source | Collection method | Destination |
|---|---|---|
| AWS CloudTrail | CloudTrail → EventBridge → Lambda → Sentinel (or Amazon Managed Service for Grafana + export) | Sentinel |
| AWS VPC Flow Logs | S3 → Kinesis Firehose → Sentinel | Sentinel |
| AWS GuardDuty | EventBridge → Lambda → Sentinel | Sentinel |
| Azure Activity Logs | Diagnostic settings → Log Analytics → Sentinel | Sentinel (native) |
| Azure NSG Flow Logs | Storage Account → Log Analytics → Sentinel | Sentinel (native) |
| GCP Cloud Audit Logs | Pub/Sub → Dataflow → Sentinel or BigQuery | Sentinel / BigQuery |
| GCP VPC Flow Logs | Cloud Logging → Sink → Pub/Sub → Sentinel | Sentinel |
| GKE/AKS Audit Logs | Managed logging (Cloud Logging / Azure Monitor) → Sentinel | Sentinel |

## Alert fatigue management

At ~100 workloads, raw CSPM output can generate thousands of findings daily. The programme manages alert fatigue through:

### 1. Severity-based routing

| CSPM severity | Action | Notification |
|---|---|---|
| Critical | Immediately pages the on-call security engineer via PagerDuty/Opsgenie. Creates a P1 Jira/GitLab issue. | PagerDuty + Slack #security-alerts + email. |
| High | Creates a GitLab issue in the security backlog. SLA: 72 hours for initial triage. | Slack #security-findings. |
| Medium | Weekly digest report. SLA: 30 days for remediation. | Monthly security review meeting. |
| Low | Quarterly report. Included in posture dashboards. | Quarterly security review. |

### 2. Deduplication and suppression

- Duplicate findings across CSPM tools are merged by resource ARN + finding type. Security Hub and Defender already deduplicate within their own scope; cross-cloud deduplication is handled in Sentinel using KQL join queries.
- Known-accepted risks (e.g., the COTS encryption exception) are suppressed in CSPM with a documented exception tag. Suppressed findings still appear in monthly reports for re-review.
- Dev/sandbox environments are excluded from Critical/High alerting. They appear in posture dashboards but do not page anyone.

### 3. Tuning cadence

- Monthly: review top-10 most-firing alerts. If a rule fires more than 50 times/month and is always benign, tune the rule or add a suppression exception.
- Quarterly: review exception register. Re-evaluate every suppression and exception.
- Post-incident: any detection gap found during incident response becomes a new detection rule within 48 hours.

## Concrete incident walkthrough: compromised CI service account

### Scenario

The wildcard-permission CI service account identified in `CLD-003` has been compromised. An attacker has used the credentials to connect to a database and exfiltrate data. The compromise was detected through anomalous CloudTrail activity.

### Detection

| Time | Event | Detection mechanism |
|---|---|---|
| T+0 | Attacker uses stolen CI credentials to call `sts:AssumeRole` and enumerate IAM roles. | GuardDuty anomaly detection flags unusual `sts:AssumeRole` pattern from the CI identity. Finding: `UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration.OutsideAWS`. |
| T+2 min | Attacker assumes `ec2policy` role (from `CLD-009`) and calls `rds:DescribeDBInstances` to locate the public database (`CLD-002`). | GuardDuty finding: `Stealth:IAMUser/CloudTrailLoggingDisabled` if CloudTrail was tampered with, or normal `AWSAPICall` in CloudTrail. Sentinel analytics rule detects `rds:Describe*` from a CI identity (unusual). |
| T+5 min | Attacker connects to the RDS MySQL instance over public endpoint using the committed password (`CLD-007`). | GuardDuty RDS Protection (if enabled) flags anomalous login. Sentinel KQL query detects login from IP outside programme's known CIDR ranges. |
| T+8 min | Attacker runs `SELECT *` queries against multiple tables. | GuardDuty RDS Protection: anomalous query pattern. Sentinel: RDS audit log shows bulk data access from unknown IP. |
| T+10 min | SOC analyst receives PagerDuty alert for GuardDuty Critical finding. | Automated: GuardDuty → EventBridge → Lambda → PagerDuty. |

### Containment (first 60 minutes)

1. **Revoke the compromised credential immediately.** Disable the CI service account / delete the access key / rotate the OIDC token. In the federation model (`../03-identity-governance/cross-cloud-iam-design.md`), this means revoking the IAM role trust or disabling the GitLab project's ability to assume the role.
2. **Block the attacker's IP at the security group / NSG level.** Add an explicit deny rule for the attacker's source IP. This is a temporary containment measure, not a permanent fix.
3. **Snapshot the affected RDS database for forensic preservation** before any further action. Take an RDS snapshot (not a backup — a point-in-time snapshot captures the current state). Tag it `forensic-evidence-{incident-id}`.
4. **Revoke all other sessions / tokens issued to the compromised identity.** If the identity was used elsewhere, those sessions are suspect.
5. **Notify the CISO and on-call platform engineer** via the incident Slack channel and phone call for Critical incidents.

### Eradication (first 24 hours)

1. **Confirm the full scope of access.** Review CloudTrail for every API call made by the compromised identity in the past 72 hours. Create a timeline. Identify every resource accessed.
2. **Rotate every credential the compromised identity had access to.** This includes database passwords, API keys, any secrets stored in Secrets Manager / Key Vault that the role could read.
3. **Fix the root cause.** Replace the wildcard IAM policy (`CLD-003`) with the scoped policy from Module 3. Remove the committed database password (`CLD-007`). Remove the public accessibility flag on the RDS instance (`CLD-002`).
4. **Scan for persistence mechanisms.** Check for: new IAM users/roles created by the attacker, new security group rules, new Lambda functions, backdoor AMIs/snapshots.

### Recovery (first 72 hours)

1. **Restore the database from a pre-compromise backup** if data integrity is in question (the attacker may have modified data, not just exfiltrated it). Use the point-in-time recovery to restore to a timestamp before the first suspicious query.
2. **Re-deploy affected workloads from known-good images.** If the attacker may have modified code or configuration on EC2 instances, terminate and replace them from the latest verified AMI.
3. **Verify all compensating controls are in place.** Network segmentation, encryption, backup retention, logging — confirm every control that should be in place actually is.
4. **Clear the incident** with the CISO and platform lead.

### Communication

| Timing | Audience | Content |
|---|---|---|
| During incident (real-time) | SOC team, on-call engineers | Incident channel: status updates every 30 minutes while active. "What we know, what we're doing, when the next update is." |
| Within 2 hours of detection | CISO, programme director | Brief verbal update: scope, immediate containment actions, whether data exfiltration is confirmed. |
| Within 24 hours | ITSO / information security governance | Written incident summary: confirmed scope, containment status, whether citizen data was affected, initial root cause. |
| Within 5 business days | Full post-incident review panel | Formal post-incident report: detailed timeline, root cause analysis, control failures, remediation actions, lessons learned, detection gap analysis. |

### Post-incident report structure

1. Executive summary
2. Timeline of events (detection → containment → eradication → recovery)
3. Root cause: wildcard IAM policy + committed database credentials + public database endpoint — three `CLD` findings chaining together
4. Impact assessment: data accessed, data modified, third-party notification requirements
5. What worked: detection time, SOC response time
6. What didn't: the wildcard policy should never have existed (Module 3 fix), the database should never have been public (Module 4 fix), the password should never have been committed (Module 2 pipeline fix)
7. Remediation actions with owners and due dates
8. Detection gap analysis: what new rules were added to prevent the same path from going undetected

## Module 1 findings addressed

| Finding | How detection addresses it |
|---|---|
| `CLD-028` (Azure logging disabled) | Flow logs and activity logs enabled on all VNets/subscriptions, sent to Sentinel. |
| `CLD-029` (Defender Free tier, alerts off) | Defender Standard tier, alert notifications enabled. |
| `CLD-024` (SQL injection/exfil alerts disabled) | Microsoft Defender for SQL alerts re-enabled. Custom Sentinel analytics rules for anomalous DB queries. |
| `CLD-016` (GKE logging off) | Cloud Logging and Cloud Monitoring enabled on all GKE clusters. Audit logs exported to Sentinel. |
| `CLD-017` (AKS logging off) | Azure Monitor Container Insights enabled on all AKS clusters. Logs exported to Sentinel. |

## Cross-references

- Findings register: `../01-findings/findings-register.md`
- Pipeline (OPA for logging resource enforcement): `../02-pipeline-supply-chain/pipeline-design.md`
- Identity governance (break-glass alerting): `../03-identity-governance/cross-cloud-iam-design.md`
- Network design (flow log collection): `../04-network-zero-trust/network-design.md`
- Remediation (fixing the root causes): `../07-remediation/remediation-advisory.md`
