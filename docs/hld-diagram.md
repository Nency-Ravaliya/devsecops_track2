flowchart TB
    subgraph DEV["Development Zone"]
        DEV_GIT[GitLab\nSource Control]
        DEV_CI[GitLab CI/CD\nShared Runner Fleet]
    end

    subgraph IDENTITY["Identity Boundary"]
        ENTRA_ID["Entra ID\nCentral IdP\nMFA + Conditional Access"]
    end

    subgraph SECRETS["Secrets & Key Management"]
        VAULT["HashiCorp Vault\nApplication Secrets"]
        AWS_KMS["AWS KMS\nCMKs per workload"]
        AZ_KV["Azure Key Vault\nCMKs per workload"]
        GCP_KMS["GCP Cloud KMS\nCMKs per workload"]
    end

    subgraph EDGE["Public Edge Tier"]
        CDN["CDN / WAF\nTLS Termination"]
        ALB["Load Balancers\nHTTPS only\nWAF_v2"]
    end

    subgraph AWS_ZONE["AWS Landing Zone\n(Production)"]
        direction TB
        subgraph AWS_SHARED["Shared Services VPC"]
            TGW["Transit Gateway"]
            NAT["NAT Gateway\n+ Network Firewall"]
            LOG_S3["Central Log Bucket\nObject Lock + CMK"]
        end
        subgraph AWS_APP["Application VPC"]
            APP_AZ1["App Subnet AZ-1\nEC2 / EKS Pods\nNo Public IPs"]
            APP_AZ2["App Subnet AZ-2\nEC2 / EKS Pods\nNo Public IPs"]
        end
        subgraph AWS_DATA["Data VPC"]
            RDS[("RDS Aurora\nPrivate Only\nEncrypted + Backup")]
            S3_APP[("S3 Bucket\nEncrypted + Versioned\nPrivate")]
        end
    end

    subgraph AZURE_ZONE["Azure Landing Zone\n(Production)"]
        direction TB
        subgraph AZURE_HUB["Hub VNet"]
            AFW["Azure Firewall\nForced Tunneling"]
            LAW["Log Analytics\nWorkspace"]
        end
        subgraph AZURE_SPOKE["Spoke VNet\n(App Tier)"]
            AKS["AKS Cluster\nRBAC + NSG\nPrivate Endpoints"]
        end
        subgraph AZURE_DATA["Data VNet"]
            MSSQL[("MSSQL Server\nPrivate Endpoint\nEncrypted")]
            BLOB[("Blob Storage\nEncrypted + Private")]
        end
    end

    subgraph GCP_ZONE["GCP Landing Zone\n(Production)"]
        direction TB
        subgraph GCP_VPC["VPC Network"]
            GKE["GKE Cluster\nRBAC + Private\nLogging Enabled"]
            CLOUD_SQL[("Cloud SQL\nPrivate IP\nEncrypted")]
            GCS[("GCS Bucket\nCMEK\nUniform Access")]
        end
        GCP_NAT["Cloud NAT\n+ Firewall Rules"]
    end

    subgraph SIEM["Centralised Detection"]
        SENTINEL["Microsoft Sentinel\nSIEM + SOAR"]
        PAGERDUTY["PagerDuty\nIncident Alerts"]
        DASH["Security Dashboard\nCSPM Posture"]
    end

    subgraph GOVERNANCE["Governance Layer"]
        OPA["OPA / Conftest\nPolicy-as-Code"]
        CHECKOV["Checkov + Trivy\nIaC Scanning"]
        DEPTRACK["Dependency-Track\nSBOM Inventory"]
    end

    %% Flows
    DEV_GIT --> ENTRA_ID
    DEV_CI -->|"OIDC Federation"| AWS_KMS
    DEV_CI -->|"Workload Identity"| AZ_KV
    DEV_CI -->|"Workload Identity Pool"| GCP_KMS
    DEV_CI --> OPA
    DEV_CI --> CHECKOV
    DEV_CI --> DEPTRACK

    ENTRA_ID -->|"SSO + JIT"| AWS_ZONE
    ENTRA_ID -->|"SSO + PIM"| AZURE_ZONE
    ENTRA_ID -->|"SSO + PAM"| GCP_ZONE

    CDN --> ALB
    ALB --> AWS_APP
    ALB --> AZURE_SPOKE
    ALB --> GCP_VPC

    AWS_APP --> AWS_DATA
    AZURE_SPOKE --> AZURE_DATA
    GCP_VPC --> GCP_VPC

    AWS_APP --> TGW
    AZURE_SPOKE --> AFW
    GCP_VPC --> GCP_NAT

    AWS_SHARED --> LOG_S3
    AZURE_HUB --> LAW
    GCP_VPC --> GCP_NAT

    LOG_S3 --> SENTINEL
    LAW --> SENTINEL
    SENTINEL --> PAGERDUTY
    SENTINEL --> DASH
