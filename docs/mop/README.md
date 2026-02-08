# Method of Procedure Index

Step-by-step procedures for deploying OpenShift with Cilium Enterprise on UCS-X hardware in an air-gapped environment.

## Deployment Model

**This deployment is fully automated via GitHub Actions pipelines.** Manual procedures are provided for reference and troubleshooting only.

### Day 0 / Day 1 / Day 2 Architecture

| Phase | Owner | Scope | Automation |
|-------|-------|-------|------------|
| **Day 0** | saif-ai-pod | UCS hardware profiles | `ucs-pipeline.yaml` |
| **Day 1** | saif-ai-pod | OCP install, IDMS bootstrap, ArgoCD bootstrap | `openshift-pipeline.yaml` |
| **Day 2** | saif-gitops | ALL operators and workloads | ArgoCD (continuous) |

**Key Principle:** Day 1 is MINIMAL. Its only job is to get a cluster to the point where ArgoCD can take over. Day 2 (GitOps) manages everything else.

## Deployment Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Automated Deployment Flow                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Day 0      │   │   Day 0      │   │   Day 1      │   │   Day 1      │ │
│  │ Prerequisites│──►│  UCS Deploy  │──►│  OCP Deploy  │──►│  Post-Install│ │
│  │  Validation  │   │  (Pipeline)  │   │  (Pipeline)  │   │  Bootstrap   │ │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘ │
│         │                  │                  │                  │          │
│         ▼                  ▼                  ▼                  ▼          │
│    Infrastructure      Server Profile     OpenShift         ArgoCD +       │
│    Requirements        + MAC Addresses    + Cilium CNI      IDMS Applied   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         Day 2 (GitOps)                                │  │
│  │                                                                       │  │
│  │   ArgoCD automatically syncs from saif-gitops:        │  │
│  │   • Full IDMS (sync-wave -10)                                        │  │
│  │   • Sealed Secrets controller (sync-wave -8)                         │  │
│  │   • CatalogSources (sync-wave -1)                                    │  │
│  │   • GPU Operator, NFD, NIM Operator                                  │  │
│  │   • Tetragon, Hubble Timescape                                       │  │
│  │   • Splunk OTEL, Vector exporter                                     │  │
│  │   • All application workloads                                        │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start (Automated)

### Full Cluster Deployment

```bash
# 1. Deploy UCS server profile
gh workflow run ucs-pipeline.yaml \
  -f operation="Activate - Apply config to server" \
  -f server_target=saif-ai-pod-1

# 2. Deploy OpenShift with Cilium (includes post-install)
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-1 \
  -f cni_type=Cilium

# 3. Wait ~90 minutes for full deployment
# ArgoCD takes over and deploys all Day 2 components automatically
```

### Existing Cluster - Re-run Post-Install Only

```bash
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-1 \
  -f validate=false \
  -f deploy=false \
  -f post_install=true \
  -f test=true
```

## Procedure Index

### Pre-Deployment (Day 0)

| Procedure | Description | Duration | Prerequisites |
|-----------|-------------|----------|---------------|
| [00-prerequisites.md](00-prerequisites.md) | Validate infrastructure, DNS, credentials | 30 min | Network access |

### Infrastructure Deployment (Day 0)

| Procedure | Description | Duration | Prerequisites |
|-----------|-------------|----------|---------------|
| [01-runner-vm-bootstrap.md](01-runner-vm-bootstrap.md) | Deploy and configure GitHub runner VM | 1 hour | Day 0 complete |
| [02-image-mirroring.md](02-image-mirroring.md) | Mirror OpenShift and operator images | 2-4 hours | Runner VM deployed |
| [03-intersight-configuration.md](03-intersight-configuration.md) | Deploy UCS server profiles | 30 min | Intersight API access |

### Cluster Deployment (Day 1)

| Procedure | Description | Duration | Prerequisites |
|-----------|-------------|----------|---------------|
| [04-openshift-installation.md](04-openshift-installation.md) | Agent-Based Installer with Cilium CNI | 90 min | Day 0 complete |

### Day 2 Operations (GitOps)

| Component | Management | Repository |
|-----------|------------|------------|
| GPU Operator | ArgoCD | saif-gitops |
| NFD Operator | ArgoCD | saif-gitops |
| NIM Operator | ArgoCD | saif-gitops |
| Tetragon | ArgoCD | saif-gitops |
| Hubble Timescape | ArgoCD | saif-gitops |
| Splunk OTEL | ArgoCD | saif-gitops |

**All Day 2 operators are GitOps-managed.** No manual installation required.

### Reference Procedures

| Procedure | Description | When to Use |
|-----------|-------------|-------------|
| [troubleshooting.md](troubleshooting.md) | Common issues and solutions | When errors occur |
| [verification-procedures.md](verification-procedures.md) | Health checks and validation | After each phase |

### Archived Procedures

| Procedure | Reason | Current Approach |
|-----------|--------|------------------|
| [archive/05-day2-cilium-migration.md](archive/05-day2-cilium-migration.md) | Cilium is now Day 1 CNI | Deployed during OCP install |
| [archive/06-day2-gpu-operator.md](archive/06-day2-gpu-operator.md) | Manual OLM deprecated | GitOps via ArgoCD |
| [archive/07-day2-argocd-gitops.md](archive/07-day2-argocd-gitops.md) | Manual install deprecated | Post-install bootstrap |

## Decision Tree

### First Deployment

```
Is infrastructure validated?
├── No  → Start at 00-prerequisites.md
└── Yes → Is runner VM deployed?
          ├── No  → Start at 01-runner-vm-bootstrap.md
          └── Yes → Are images mirrored?
                    ├── No  → Run sync-images workflow (saif-sys-admin)
                    └── Yes → Is UCS profile deployed?
                              ├── No  → Run ucs-pipeline.yaml
                              └── Yes → Run openshift-pipeline.yaml
```

### Adding Another Cluster

If runner VM and registry already exist:

```bash
# 1. Update cluster-mappings.yaml with new cluster definition
# 2. Run UCS pipeline
gh workflow run ucs-pipeline.yaml \
  -f operation="Activate - Apply config to server" \
  -f server_target=saif-ai-pod-X

# 3. Run OpenShift pipeline
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-X \
  -f cni_type=Cilium
```

### Updating Day 2 Components

All Day 2 changes go through GitOps:

1. Edit manifests in `saif-gitops`
2. Push to main branch
3. ArgoCD automatically syncs changes

**No workflow runs required for Day 2 changes.**

## What Changed from Original MOP

| Original | Current |
|----------|---------|
| OVN CNI → Cilium migration (Day 2) | Cilium deployed as Day 1 CNI |
| Manual GPU Operator install | GitOps-managed via ArgoCD |
| Manual ArgoCD install | Post-install bootstrap (automated) |
| Manual IDMS application | Post-install bootstrap + GitOps IDMS |
| Separate Day 2 procedures | Single pipeline + GitOps |

## Related Documentation

- [../architecture/TOPOLOGY.md](../architecture/TOPOLOGY.md) - Infrastructure reference (IPs, VLANs, hardware)
- [../CUSTOMIZATION.md](../CUSTOMIZATION.md) - Adapting for different environments
