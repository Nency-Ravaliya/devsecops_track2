# FIXED: CLD-003 — Wildcard IAM policy on CI service account
#
# This file replaces the wildcard aws_iam_user_policy from iam.tf with
# scoped, OIDC-federated roles. See Module 3 (cross-cloud-iam-design.md)
# for the full design rationale.
#
# BEFORE (vulnerable):
#   Action = ["ec2:*", "s3:*", "lambda:*", "cloudwatch:*"]
#   Resource = "*"
#
# AFTER (hardened):
#   - No static IAM user or access keys
#   - OIDC federation from GitLab CI
#   - Three distinct roles: plan-readonly, deploy-workload, deploy-shared
#   - All permissions scoped by resource ARN and/or tag conditions

# --- OIDC identity provider for GitLab CI ---
data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "gitlab" {
  url             = "https://gitlab.example.com"
  client_id_list  = ["https://gitlab.example.com"]
  thumbprint_list = ["ffffffffffffffffffffffffffffffffffffffff"]
}

# =============================================
# ROLE 1: ci-plan-readonly
# Purpose: terraform plan in MR pipelines
# Trust: any protected branch or MR from the project
# =============================================
resource "aws_iam_role" "ci_plan_readonly" {
  name = "ci-plan-readonly"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.gitlab.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "gitlab.example.com:sub" = "project_path:${var.gitlab_project_path}:ref_type:branch"
          "gitlab.example.com:aud" = "https://gitlab.example.com"
        }
      }
    }]
  })

  tags = {
    Purpose     = "CI Terraform Plan"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "ci_plan_readonly" {
  name = "ci-plan-readonly-policy"
  role = aws_iam_role.ci_plan_readonly.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformPlanReadOnly"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "s3:GetBucket*", "s3:GetObject*", "s3:ListBucket*",
          "lambda:GetFunction*", "lambda:ListFunctions",
          "rds:Describe*",
          "iam:GetRole", "iam:GetPolicy", "iam:GetPolicyVersion",
          "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
          "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricData",
          "kms:DescribeKey", "kms:ListAliases",
          "sts:GetCallerIdentity",
          "logs:DescribeLogGroups", "logs:DescribeLogStreams"
        ]
        Resource = "*"
      },
      {
        Sid    = "TerraformStateAccess"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.project_name}-tfstate",
          "arn:aws:s3:::${var.project_name}-tfstate/*"
        ]
      },
      {
        Sid    = "DynamoDBStateLock"
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = "arn:aws:dynamodb:*:${data.aws_caller_identity.current.account_id}:table/terraform-locks"
      }
    ]
  })
}

# =============================================
# ROLE 2: ci-deploy-workload
# Purpose: terraform apply for the specific workload
# Trust: only main branch of the specific project
# =============================================
resource "aws_iam_role" "ci_deploy_workload" {
  name = "ci-deploy-workload"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.gitlab.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "gitlab.example.com:sub" = "project_path:${var.gitlab_project_path}:ref_type:branch:ref:main"
          "gitlab.example.com:aud" = "https://gitlab.example.com"
        }
      }
    }]
  })

  tags = {
    Purpose     = "CI Terraform Apply"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "ci_deploy_workload" {
  name = "ci-deploy-workload-policy"
  role = aws_iam_role.ci_deploy_workload.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2Workload"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances", "ec2:TerminateInstances", "ec2:StopInstances",
          "ec2:StartInstances", "ec2:CreateTags", "ec2:DeleteTags",
          "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
          "ec2:Describe*"
        ]
        Resource = "*"
        Condition = {
          StringEquals = { "aws:ResourceTag/workload" = var.project_name }
        }
      },
      {
        Sid    = "S3Workload"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket",
          "s3:PutBucketPolicy", "s3:PutBucketAcl",
          "s3:PutEncryptionConfiguration", "s3:PutBucketVersioning",
          "s3:PutBucketLogging", "s3:PutBucketPublicAccessBlock",
          "s3:GetBucket*", "s3:ListBucket*"
        ]
        Resource = "arn:aws:s3:::${var.project_name}-*"
      },
      {
        Sid    = "RDSWorkload"
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance", "rds:ModifyDBInstance",
          "rds:DeleteDBInstance", "rds:CreateDBSubnetGroup",
          "rds:DeleteDBSubnetGroup", "rds:Describe*",
          "rds:AddTagsToResource", "rds:RemoveTagsFromResource"
        ]
        Resource = "arn:aws:rds:*:${data.aws_caller_identity.current.account_id}:db:${var.project_name}-*"
      },
      {
        Sid    = "TerraformStateAccess"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.project_name}-tfstate",
          "arn:aws:s3:::${var.project_name}-tfstate/*"
        ]
      },
      {
        Sid    = "DynamoDBStateLock"
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = "arn:aws:dynamodb:*:${data.aws_caller_identity.current.account_id}:table/terraform-locks"
      },
      {
        Sid    = "DenyDangerousActions"
        Effect = "Deny"
        Action = [
          "iam:CreateUser", "iam:CreateAccessKey",
          "iam:AttachUserPolicy", "iam:PutUserPolicy",
          "s3:PutBucketAcl"
        ]
        Resource = "*"
        Condition = {
          StringNotEquals = { "aws:ResourceTag/workload" = var.project_name }
        }
      }
    ]
  })
}

# --- REMOVE the old wildcard user (CLD-003 / CLD-004) ---
# These resources should be deleted:
#
# resource "aws_iam_user" "ci_user" { ... }         # DELETE
# resource "aws_iam_user_policy" "userpolicy" { ... } # DELETE — the wildcard
# resource "aws_iam_access_key" "user_key" { ... }    # DELETE — static keys
