# Module 4 — Network Security & Zero-Trust Architecture

## Context

The programme runs ~100 workloads across two landing zone tiers — older account-per-environment and newer landing-zone-accelerator-style with centralised logging. The audit found internet-exposed databases (`CLD-002`, `CLD-012`), SSH/RDP open to the world (`CLD-013`, `CLD-014`, `CLD-015`), and no network-level segmentation enforcing workload separation. Azure and GCP are coming onboarding into the same model later this year.

This module designs a target-state network architecture that works across AWS, Azure, and GCP as one governance model, not three disconnected network philosophies.

## Design principles

1. **No workload talks to the internet directly.** All ingress goes through a centralised, auditable edge (load balancer, WAF, CDN). All egress goes through a managed NAT/firewall with inspection.
2. **Workload isolation by sensitivity tier.** Network segments are enforced by VPC/VNet, not just security group or firewall rules. A compromised workload in one tier cannot route to another tier.
3. **Private endpoints for all data services.** Databases, object storage, and message queues are accessed only through private endpoints or VPC/VNet service endpoints — never through public IPs.
4. **Zero trust at the workload level.** Even within the same network segment, workloads authenticate each other via mTLS or identity-based policies, not implicit network trust.

## Segmentation strategy

### Three network tiers

| Tier | Purpose | Workload examples | Network treatment |
|---|---|---|---|
| **Public edge** | Internet-facing entry point only. No application logic runs here. | Application Load Balancer, WAF, CDN, API Gateway | Public subnets with strict ingress only from approved CIDRs. No outbound to internet. |
| **Application** | All compute — VMs, containers, Lambda, App Service. | EC2 web/app hosts, EKS pods, Lambda, AKS workloads, GKE pods, Azure App Service | Private subnets. No public IPs. Access to internet via NAT only. No inbound from internet. |
| **Data** | Managed databases, object storage, message queues. | RDS, Aurora, Cosmos DB, Cloud SQL, Neptune, S3 with private endpoint, GCS | Private subnets with no internet route at all. Access only from application tier via private endpoints/service endpoints. |

### Within-cloud isolation: shared services VPC/VNet

Each cloud gets a dedicated **shared services VPC/VNet** that hosts:

- Centralised logging bucket (S3 / Storage Account / GCS)
- Transit gateway / VNet hub / Cloud Hub (see cross-cloud below)
- VPN/firewall appliances if deployed
- Bastion or jump-host subnets (being phased out in favour of SSM/Bastion)

### Cross-tier connectivity

Within a cloud, the shared services hub routes traffic between tiers using a transit gateway (AWS), VNet hub (Azure), or VPC Network + Cloud NAT (GCP). Each workload VPC/VNet is attached to the hub with explicit route tables.

**AWS example:**

```
workload-vpc-app  ──── AWS Transit Gateway ──── workload-vpc-data
     │                                               │
     └──── route tables allow only:                   └── route to data tier via TGW
           10.20.0.0/16 (app tier CIDR)
           0.0.0.0/0 → NAT GW (egress only)
```

**Azure example:**

```
workload-vnet-app  ──── Hub VNet (firewall) ──── workload-vnet-data
     │                     │                       │
     └── UDR routes to     └── forced tunneling    └── UDR routes only to
         hub firewall          for internet            hub firewall, no
                                                      direct internet
```

**GCP example:**

```
workload-vpc-app  ──── Hub-and-spoke via VPC peering ──── workload-vpc-data
     │                                                         │
     └── Cloud NAT for egress                                   └── No internet route
         No internet ingress
```

## Cross-cloud connectivity

When Azure and GCP are onboarded, cross-cloud connectivity for shared services (SIEM, identity, GitLab) uses:

| Connection | AWS ↔ Azure | AWS ↔ GCP | Azure ↔ GCP |
|---|---|---|---|
| **Mechanism** | AWS Transit Gateway ↔ Azure ExpressRoute via Megaport/Equinix, or site-to-site VPN as interim | AWS Transit Gateway ↔ GCP Cloud Interconnect via Megaport, or site-to-site VPN | Azure ExpressRoute ↔ GCP Cloud Interconnect, or site-to-site VPN |
| **What traverses** | Centralised logging replication, CI/CD artifact sync, shared identity tokens. NOT runtime workload traffic. | Same as AWS↔Azure | Same |
| **Not connected** | Workload-to-workload traffic between clouds. This is not an active-active multi-cloud application mesh — it is separate clouds with shared governance. | Same | Same |

**Explicit decision: no cross-cloud runtime traffic path.** The programme is migrating workloads into a consistent governance model, not building a single multi-cloud application. Each workload runs in one cloud. Cross-cloud links exist only for governance traffic (logging, identity, CI/CD).

## Egress control

The audit trigger and Module 1 findings show no egress restrictions anywhere. The target state:

| Cloud | Egress mechanism | What it controls |
|---|---|---|
| **AWS** | NAT Gateway per availability zone + AWS Network Firewall or third-party (Palo Alto, Fortinet) inline. Outbound rules restrict to known destinations: package registries, cloud APIs, approved SaaS endpoints. | All workload internet egress is forced through the firewall. DNS is resolved via Route 53 Resolver outbound endpoint with DNS firewall rules. |
| **Azure** | Azure Firewall in the Hub VNet. User-defined routes (UDRs) on workload subnets force all traffic through the firewall. Azure Firewall Premium for TLS inspection if compliance requires it. | Same model as AWS — forced tunneling through a managed firewall with explicit allow-listing. |
| **GCP** | Cloud NAT for outbound + Cloud DNS + hierarchical firewall policies. Egress is restricted at the VPC level; workloads in data tier have no internet route at all. | Same — no direct internet access. Egress through Cloud NAT with firewall rules filtering destination ranges. |

### Egress policy by workload tier

| Tier | Egress allowed | Destination | Justification |
|---|---|---|---|
| **Public edge** | Inbound from internet, outbound to application tier only | Internal CIDRs | Edge layer terminates TLS, forwards to application tier. No direct internet egress needed. |
| **Application** | Package registries, cloud APIs, approved SaaS, monitoring endpoints | Approved CIDR list via firewall rule | Needed for deployment, runtime dependencies, and telemetry. No SSH/SCP outbound. |
| **Data** | No internet egress at all | None | Databases and storage should never initiate outbound connections to the internet. |

## How this avoids becoming three separate network philosophies

| Aspect | What stays consistent | What necessarily differs |
|---|---|---|
| **Tier model** | Three tiers (edge / application / data) enforced identically. Same naming, same traffic flow pattern. | VPC vs VNet vs VPC naming — but the concept is identical. |
| **Private endpoints** | All data services accessed only through private endpoints. No public IPs on databases. | AWS uses VPC endpoints (Gateway/Interface), Azure uses Private Link, GCP uses Private Service Connect. Implementation differs; policy is identical. |
| **Forced egress** | All workload internet access goes through a centralised firewall/NAT. No direct egress. | AWS Network Firewall, Azure Firewall, GCP Cloud Firewall — different managed services, same architecture. |
| **Segmentation enforcement** | Isolation by VPC/VNet, not just security groups. Hub-and-spoke topology. | AWS Transit Gateway, Azure Hub-Spoke, GCP VPC peering — different transit mechanisms, same topology. |
| **Zero trust at workload** | mTLS between services within the same tier (Istio on EKS/AKS/GKE, or AWS App Mesh equivalent). | Service mesh implementation varies; Istio is common across EKS and AKS. GKE uses Anthos Service Mesh (managed Istio). |
| **Policy governance** | OPA/Conftest evaluates firewall rules, NSGs, and security groups against a single policy set in the pipeline (`../02-pipeline-supply-chain/pipeline-design.md`). | Policy input shapes differ per provider (AWS security group vs Azure NSG vs GCP firewall rule), but the OPA Rego evaluates the same intent (e.g., "no ingress from 0.0.0.0/0 to port 22"). |

## Module 1 findings addressed by this design

| Finding | How network design addresses it |
|---|---|
| `CLD-013` (AWS SSH open to internet) | Application tier has no public IPs. SSH replaced by SSM Session Manager or Azure Bastion. |
| `CLD-014` (Azure NSG open SSH/RDP) | NSG rules default-deny inbound. Management through Bastion/JIT. |
| `CLD-015` (GCP firewall all TCP open) | Hierarchical firewall policies default-deny. IAP for admin access. |
| `CLD-002` (AWS RDS public) | Data tier has no internet route. RDS only accessible from application tier via private subnet. |
| `CLD-012` (GCP Cloud SQL public) | Private IP only. No `authorized_networks` with 0.0.0.0/0. |
| `CLD-028` (Azure logging disabled) | Network flow logs enabled on all hub and spoke VNets, sent to central Log Analytics. |

## Cross-references

- Findings register: `../01-findings/findings-register.md`
- CI/CD pipeline (OPA policies for network): `../02-pipeline-supply-chain/pipeline-design.md`
- Identity governance (workload federation, SSM/Bastion): `../03-identity-governance/cross-cloud-iam-design.md`
- Data protection (private endpoints, encryption in transit): `../05-data-protection/encryption-key-mgmt.md`
- Detection and IR (flow log collection, firewall log centralisation): `../06-detection-ir/monitoring-ir-plan.md`
- Architecture diagrams: `../10-architecture/hld-diagram.mmd`, `../10-architecture/lld-diagram.mmd`
