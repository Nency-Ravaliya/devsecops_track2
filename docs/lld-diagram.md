flowchart TB
    subgraph GITLAB["GitLab CI/CD"]
        MR["Merge Request\nPipeline"]
        PROD["Production Pipeline\nManual Trigger"]
    end

    subgraph AWS_API["AWS API Layer"]
        STS["AWS STS\nOIDC Federation"]
        S3_STATE[("S3: tfstate\nEncrypted + Versioned\nPrivate Bucket")]
        DDB[("DynamoDB\nState Lock Table")]
    end

    subgraph AWS_ACCOUNT["AWS Account: production-001"]
        subgraph VPC_APP["Application VPC\n10.20.0.0/16"]
            subgraph PUBLIC_SUBNET["Public Subnet\n10.20.1.0/24"]
                ALB["ALB\nHTTPS :443\nACM Cert\nWAF_v2 attached"]
            end
            subgraph APP_SUBNET_A["App Subnet AZ-a\n10.20.10.0/24"]
                EC2_A["EC2: db-app\nInstance Profile:\nci-deploy-workload\nIMDSv2 enforced\nSSM Agent running"]
            end
            subgraph APP_SUBNET_B["App Subnet AZ-b\n10.20.11.0/24"]
                EC2_B["EC2: db-app\nStandby AZ\nSame role + config"]
            end
            TGW["Transit Gateway\nAttachment"]
            NAT["NAT Gateway\n+ Network Firewall\nEgress: approved CIDRs only"]
        end

        subgraph VPC_DATA["Data VPC\n10.30.0.0/16"]
            subgraph RDS_SUBNET_A["RDS Subnet AZ-a\n10.30.10.0/24"]
                RDS_A[("RDS Primary\nMySQL 8.0\nstorage_encrypted=true\nKMS CMK\nMulti-AZ\nbackup_retention=7\nrds.force_ssl=1")]
            end
            subgraph RDS_SUBNET_B["RDS Subnet AZ-b\n10.30.11.0/24"]
                RDS_B[("RDS Standby\nAuto-failover")]
            end
            S3_LOGS[("S3: central-logs\nObject Lock: Governance\nCMK encrypted\nAccess logging enabled")]
        end

        subgraph SHARED["Shared Services VPC\n10.10.0.0/16"]
            CW_LOGS["CloudWatch Logs\nLog Group\nRetention: 365 days"]
            GUARDDUTY["GuardDuty\nDetective\nRDS Protection enabled"]
            SECRETS["Secrets Manager\nDB Password\nCMK encrypted\nRotation enabled"]
        end
    end

    subgraph SOC["SOC / Detection"]
        SENTINEL["Sentinel\nCloudTrail + GuardDuty\n+ VPC Flow Logs\n+ RDS Audit Logs"]
        PAGERDUTY["PagerDuty\nCritical: pages\nHigh: Slack alert"]
    end

    subgraph ENTRID["Identity"]
        ENTRA["Entra ID\nSSO + MFA\nConditional Access"]
        IAM_SSM["IAM Identity Center\nSSO → EC2 SSM\nPermission Set:\nssm-session-manager"]
    end

    %% CI/CD flow
    MR -->|"terraform plan"| STS
    STS -->|"AssumeRole\n15min token"| S3_STATE
    S3_STATE --> DDB
    PROD -->|"terraform apply\nafter approval"| STS

    %% Identity flow
    ENTRA --> IAM_SSM
    IAM_SSM -->|"SSM Start Session"| EC2_A
    ENTRA -->|"OIDC federated\nCI roles"| STS

    %% Runtime data flow
    ALB -->|"HTTPS :443\nTLS 1.3"| EC2_A
    ALB -->|"HTTPS :443\nfailover"| EC2_B
    EC2_A -->|"MySQL :3306\nTLS forced\nvia rds.force_ssl"| RDS_A
    EC2_A -.->|"failover"| RDS_B
    EC2_A -->|"HTTPS :443\nSecrets API"| SECRETS

    %% Logging flow
    EC2_A -->|"VPC Flow Logs\n+ RDS Audit Logs"| CW_LOGS
    CW_LOGS --> SENTINEL
    GUARDDUTY --> SENTINEL
    RDS_A -.->|"CloudTrail\ndata events"| GUARDDUTY
    SENTINEL --> PAGERDUTY

    %% Egress
    EC2_A -->|"outbound\nvia NAT"| NAT

    %% Encryption annotations
    RDS_A -.- KMS_NOTE["KMS CMK\nenable_key_rotation=true\nKey policy: workload-scoped"]
    S3_STATE -.- S3_NOTE["SSE-KMS\nBucket policy:\ndeny unencrypted uploads\ndeny public access"]
    SECRETS -.- SM_NOTE["CMK encrypted\nRotation: 90 days\nNo plaintext in state"]
