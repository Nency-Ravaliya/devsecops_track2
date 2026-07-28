# Module 3 — Identity & Access Governance Across Clouds

## Context

The programme runs roughly 100 workloads today, mostly on AWS, with Azure and GCP onboarding planned later this year. Terraform is provisioned through self-managed GitLab CI/CD. The audit trigger in `../01-findings/findings-register.md` includes an IAM policy with wildcard permissions attached to a CI service account (`CLD-003`), a similarly broad EC2 instance role (`CLD-009`), and an Azure custom role granting `actions = ["*"]` at subscription scope (`CLD-010`). These are not edge cases — they are symptoms of an identity model that never had cross-cloud governance built in.

This module designs a unified identity governance model that applies across all three clouds rather than three disconnected IAM strategies.

## Design principles

1. **No standing privilege.** Every elevated permission is time-bound, approval-gated, or both. Permanent admin rights exist only for break-glass accounts whose use is tightly monitored.
2. **Workload identity over secrets.** CI/CD pipelines and cloud workloads use federation and short-lived credentials rather than long-lived keys or service account JSON files.
3. **One governance surface, three implementations.** Policy decisions are centralised (who can access what, under what conditions), but enforcement uses native cloud IAM constructs because each provider's model is different enough that abstraction layers create more confusion than they solve.
4. **Least privilege by default, with explicit escalation paths.** The base permission set is read-only for humans and scoped to the exact deployment actions for CI. Anything beyond that requires a time-bound elevation.

## Workload identity federation

### Why federation over long-lived credentials

Long-lived credentials — IAM user access keys, Azure service principal secrets, GCP service account JSON keys — are the root cause of several Module 1 findings:

- `CLD-003`: Wildcard permissions attached to what amounts to a CI service account.
- `CLD-004`: Static AWS access keys committed in the Terraform provider block.
- `CLD-005`, `CLD-006`: Static AWS keys in EC2 user data and Lambda environment variables.

Federation removes the credential itself. The CI system proves its identity through an OIDC token, and the cloud provider issues short-lived credentials scoped to the pipeline's current job. If the OIDC token leaks, it expires in minutes rather than remaining valid indefinitely.

### Implementation per cloud

| Cloud | Federation mechanism | CI/CD identity source | Token lifetime |
|---|---|---|---|
| **AWS** | GitLab → AWS STS `AssumeRoleWithWebIdentity` via an OIDC identity provider registered in IAM. | GitLab CI job JWT, with claims including `project_path`, `ref`, `pipeline_source`, and `environment`. | 15–60 minutes (configured on the IAM role trust policy). |
| **Azure** | GitLab → Azure Workload Identity Federation via a federated identity credential on an Azure AD (Entra ID) application registration. | Same GitLab CI JWT. Azure matches `issuer`, `subject`, and optional claims. | Token validity matches Azure's default (60–90 minutes). |
| **GCP** | GitLab → GCP Workload Identity Federation via a Workload Identity Pool and Provider. The pool trusts the GitLab OIDC issuer, and attribute mapping controls which GitLab projects can assume which GCP service accounts. | Same GitLab CI JWT. | 60 minutes (default STS session). |

### Trust boundaries and conditions

The trust policy on each cloud role must be constrained:

**AWS example (IAM role trust policy):**

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/gitlab.example.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "gitlab.example.com:sub": "project_path:platform/workload-alpha:ref_type:branch:ref:main",
        "gitlab.example.com:aud": "https://gitlab.example.com"
      }
    }
  }]
}
```

Key constraint: the `sub` claim pins the trust to a specific GitLab project path and branch. A merge request from a different project or an unprotected branch cannot assume the role.

**Azure example (federated identity credential):**

```json
{
  "name": "gitlab-ci-workload-alpha",
  "issuer": "https://gitlab.example.com",
  "subject": "project_path:platform/workload-alpha:ref_type:branch:ref:main",
  "audiences": ["https://gitlab.example.com"]
}
```

**GCP example (Workload Identity Pool attribute condition):**

```yaml
attribute_condition: >
  assertion.sub == "project_path:platform/workload-alpha:ref_type:branch:ref:main"
```

### What this replaces

All static CI credentials — AWS IAM user access keys, Azure service principal secrets, GCP service account JSON keys exported as CI/CD variables — are deleted after federation is validated. The pipeline design in `../02-pipeline-supply-chain/pipeline-design.md` already assumes OIDC federation for provider authentication.

## Specific redesign of the wildcard CI service account (`CLD-003`)

The audit found an IAM policy granting `ec2:*`, `s3:*`, `lambda:*`, and `cloudwatch:*` on all resources (`*`). This section replaces that policy with a concrete, scoped alternative.

### Replacement identity architecture

Instead of one user with one broad policy, the CI pipeline uses **three separate IAM roles**, each assumed via OIDC federation with different trust constraints:

| Role | Purpose | Trust constraint | Permissions |
|---|---|---|---|
| `ci-plan-readonly` | `terraform plan` and validation in MR pipelines | Any protected branch or MR from the project | Read-only across the services the workload touches. No write capability. |
| `ci-deploy-workload` | `terraform apply` for the specific workload | Only the `main` branch of the specific project, only in approved deploy pipelines | Scoped write permissions for the workload's own resources. |
| `ci-deploy-shared-infra` | Changes to shared infrastructure (VPC, transit gateway, central logging) | Only the `main` branch of the `platform/shared-infra` project, with manual approval gate | Broader write permissions but still constrained to shared infrastructure resource ARNs. |

### Replacement permission sets

**`ci-plan-readonly` (replaces the read side of CLD-003):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformPlanReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "s3:GetBucket*", "s3:GetObject*", "s3:ListBucket*",
        "lambda:GetFunction*", "lambda:ListFunctions",
        "rds:Describe*",
        "iam:GetRole", "iam:GetPolicy", "iam:GetPolicyVersion",
        "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
        "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricData",
        "kms:DescribeKey", "kms:ListAliases",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "TerraformStateAccess",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::workload-alpha-tfstate",
        "arn:aws:s3:::workload-alpha-tfstate/*"
      ]
    },
    {
      "Sid": "DynamoDBStateLock",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"],
      "Resource": "arn:aws:dynamodb:*:ACCOUNT_ID:table/terraform-locks"
    }
  ]
}
```

**`ci-deploy-workload` (replaces the write side of CLD-003):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2WorkloadDeploy",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances", "ec2:TerminateInstances", "ec2:StopInstances",
        "ec2:StartInstances", "ec2:CreateTags", "ec2:DeleteTags",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
        "ec2:Describe*"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {"aws:ResourceTag/workload": "alpha"}
      }
    },
    {
      "Sid": "S3WorkloadBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket", "s3:DeleteBucket",
        "s3:PutBucketPolicy", "s3:PutBucketAcl",
        "s3:PutEncryptionConfiguration", "s3:PutBucketVersioning",
        "s3:PutBucketLogging", "s3:PutBucketPublicAccessBlock",
        "s3:GetBucket*", "s3:ListBucket*"
      ],
      "Resource": "arn:aws:s3:::workload-alpha-*"
    },
    {
      "Sid": "LambdaWorkloadDeploy",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction", "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction",
        "lambda:GetFunction*", "lambda:ListFunctions",
        "lambda:AddPermission", "lambda:RemovePermission",
        "lambda:TagResource", "lambda:UntagResource"
      ],
      "Resource": "arn:aws:lambda:*:ACCOUNT_ID:function:alpha-*"
    },
    {
      "Sid": "RDSWorkloadDeploy",
      "Effect": "Allow",
      "Action": [
        "rds:CreateDBInstance", "rds:ModifyDBInstance",
        "rds:DeleteDBInstance", "rds:CreateDBSubnetGroup",
        "rds:DeleteDBSubnetGroup", "rds:Describe*",
        "rds:AddTagsToResource", "rds:RemoveTagsFromResource"
      ],
      "Resource": "arn:aws:rds:*:ACCOUNT_ID:db:alpha-*"
    },
    {
      "Sid": "DenyDangerousActions",
      "Effect": "Deny",
      "Action": [
        "iam:CreateUser", "iam:CreateAccessKey",
        "iam:AttachUserPolicy", "iam:PutUserPolicy",
        "s3:PutBucketAcl",
        "rds:ModifyDBInstance"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {"aws:ResourceTag/workload": "alpha"}
      }
    }
  ]
}
```

The critical difference from CLD-003: permissions are scoped to the workload's resources by tag condition and ARN pattern, not granted on `*`. The deny statement provides a guardrail against accidental cross-workload changes. IAM mutation (creating users, attaching policies) is blocked entirely for workload deploy roles.

### Azure equivalent (`CLD-010` redesign)

The Azure custom role with `actions = ["*"]` is replaced with a workload-scoped custom role at the resource group level:

```json
{
  "Name": "ci-deploy-workload-alpha",
  "Description": "CI deploy role for workload alpha, scoped to its resource group",
  "Actions": [
    "Microsoft.Compute/virtualMachines/*",
    "Microsoft.Network/virtualNetworks/read",
    "Microsoft.Network/networkSecurityGroups/*",
    "Microsoft.Storage/storageAccounts/*",
    "Microsoft.Sql/servers/read",
    "Microsoft.Sql/servers/databases/*",
    "Microsoft.Resources/deployments/*",
    "Microsoft.Resources/subscriptions/resourceGroups/read"
  ],
  "NotActions": [
    "Microsoft.Authorization/*",
    "Microsoft.Network/virtualNetworks/write",
    "Microsoft.Network/virtualNetworks/delete"
  ],
  "AssignableScopes": [
    "/subscriptions/SUB_ID/resourceGroups/rg-workload-alpha"
  ]
}
```

`NotActions` blocks IAM and networking changes that should require platform team review. The assignable scope is limited to the workload's resource group.

## Human access model

### Day-to-day access

All engineers authenticate through a central identity provider (IdP) — typically Microsoft Entra ID (Azure AD) for government programmes because it supports conditional access, device compliance, and FIDO2/phishing-resistant MFA.

| Access level | Who | How they authenticate | What they can do |
|---|---|---|---|
| **Read-only** | All engineers, support, audit | SSO via IdP → federated into each cloud. | View console resources, read logs, describe infrastructure. No write, no data-plane access. |
| **Workload operator** | Application team members | SSO + time-bound role elevation (see JIT below). | Restart services, read application logs, manage workload-scoped resources. |
| **Platform engineer** | Landing zone / infrastructure team | SSO + time-bound elevation through PIM/Assume Role. | Modify shared infrastructure, networking, landing zone configuration. |
| **Security / audit** | Security team | SSO + read-only security tooling access (Security Hub, Defender, SCC). | Review security findings, monitor alerts, initiate investigations. |

### SSO federation per cloud

| Cloud | Federation mechanism | Session limit |
|---|---|---|
| AWS | Entra ID → AWS IAM Identity Center (SSO) via SAML. Users select permission sets and accounts from the SSO portal. Short-lived role credentials issued per session. | 1–4 hours (configurable per permission set). |
| Azure | Entra ID native. Users access Azure resources directly after IdP authentication. MFA required. | 1 hour for PIM-elevated roles. |
| GCP | Entra ID → Google Cloud Identity via SAML, or Entra ID → GCP Workforce Identity Federation (OIDC). Users access GCP console or `gcloud` CLI through federated login. | 1 hour for elevated sessions. |

### Privileged / admin access: just-in-time (JIT) elevation

Standing admin access does not exist in the target state. Privileged actions require explicit, time-bound elevation:

**AWS:** AWS IAM Identity Center permission sets are configured with a maximum session duration (1–4 hours). Elevated permission sets (e.g., `AdministratorAccess`) require an approval workflow through a custom ServiceNow / GitLab issue integration or through AWS Identity Center's built-in request-approval mechanism. AWS CloudTrail logs all `AssumeRole` events for the elevated session.

**Azure:** Microsoft Entra Privileged Identity Management (PIM) controls role activation. When an engineer needs to modify networking or IAM configuration, they request activation of the relevant role assignment in PIM. The activation requires:

- MFA re-authentication.
- Justification text (linked to a change request or incident).
- Approval from a designated approver (for roles above Contributor).
- Maximum activation duration of 1–4 hours.

PIM creates an audit log entry for every activation, deactivation, and denial.

**GCP:** GCP does not have a native PIM equivalent. The programme should use one of:

- **PAM (Privileged Access Manager)** — GCP's built-in JIT access tool that allows users to request temporary grants with approval workflows and expiry. Available in Security Command Center Premium tier.
- If PAM is not available: a custom elevation workflow using a Cloud Function that grants the requesting user the needed IAM binding with an expiry condition, triggered via a Slack or ServiceNow approval flow, and logged through Cloud Audit Logs.

### Break-glass / emergency access

Break-glass access exists for scenarios where SSO, the IdP, or the JIT elevation system is unavailable.

**Design:**

1. **One break-glass account per cloud per critical account/subscription/project.** Not per engineer — break-glass accounts are shared emergency access, not personal identities.
2. **Credentials stored in a hardware security module or a physically isolated vault.** Not in a password manager, not in a CI variable, not in a shared drive. For AWS: a sealed envelope in a physical safe containing the root account password and a hardware MFA device. For Azure: a separate Entra ID emergency access account with a FIDO2 key. For GCP: a super-admin account with a hardware security key.
3. **Break-glass use triggers immediate, irrevocable alerting.** The alerts go to a distribution list that includes the CISO, platform lead, and on-call security engineer. The alert cannot be suppressed by the break-glass user.
4. **Post-incident review within 24 hours.** Every break-glass session is reviewed, the reason is documented, and the session's actions are audited against CloudTrail / Azure Activity Log / GCP Cloud Audit Logs.
5. **Regular testing.** Break-glass accounts are tested quarterly to confirm they work, credentials are still valid, alerting fires correctly, and the process is documented.

**Monitoring implementation:**

| Cloud | Detection | Alert target |
|---|---|---|
| AWS | CloudTrail event `ConsoleLogin` by root or `sts:AssumeRole` for break-glass role → CloudWatch alarm → SNS topic. | SOC email + PagerDuty/Slack. |
| Azure | Entra ID sign-in log for the emergency access account → Azure Monitor alert rule → Action Group. | SOC email + PagerDuty/Slack. |
| GCP | Cloud Audit Log for super-admin actions → Log-based alert → Cloud Monitoring notification channel. | SOC email + PagerDuty/Slack. |

## Access review and hygiene

| Activity | Cadence | Tooling |
|---|---|---|
| Unused IAM roles / permission sets | Monthly | AWS IAM Access Analyzer, Azure Entra access reviews, GCP IAM Recommender. |
| Service account key age (where federation cannot be used) | Weekly alert if key > 90 days | AWS Config rule `iam-access-key-rotation`, Azure Policy, GCP org policy `iam.disableServiceAccountKeyCreation`. |
| Wildcard / broad permission audit | Quarterly | Checkov CKV_AWS_1/62, OPA policies (see `../02-pipeline-supply-chain/pipeline-design.md`), custom Access Analyzer queries. |
| Break-glass account test | Quarterly | Manual — documented in runbook. |
| Workload tier classification review | Quarterly | Platform team reviews `workload-tiers.yml`. |

## How this relates to other modules

- `CLD-003`, `CLD-009`, `CLD-010`: The wildcard CI identity, broad EC2 role, and Azure wildcard custom role are directly redesigned above.
- `CLD-004`, `CLD-005`, `CLD-006`: Hardcoded credentials are eliminated by workload identity federation.
- Pipeline design (`../02-pipeline-supply-chain/pipeline-design.md`): Module 2 assumes OIDC federation for provider authentication. This module provides the concrete IAM architecture the pipeline authenticates into.
- Network design (`../04-network-zero-trust/network-design.md`): Network segmentation and zero-trust policies interact with identity conditions — IAM policies may include VPC endpoint conditions or network source restrictions.
- Detection and IR (`../06-detection-ir/monitoring-ir-plan.md`): Break-glass alerting and JIT elevation logging feed into the SIEM and detection workflows.
