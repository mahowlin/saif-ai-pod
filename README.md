# SAIF AI Pod

Day 0 and Day 1 automation for deploying air-gapped Single Node OpenShift on Cisco UCS-X with NVIDIA L40S GPUs and Cilium Enterprise CNI.

## Overview

This repository automates the full lifecycle of bare-metal OpenShift clusters:

- **Day 0**: Cisco Intersight server profile management via Terraform
- **Day 1**: Agent-based OpenShift installation with Cilium CNI
- **Post-install**: IDMS application and ArgoCD bootstrap for Day 2 handoff

## Architecture

```
Phase 0        Phase 1        Phase 2        Phase 3
Runner VM  --> Intersight --> OpenShift  --> Day 2 Ops
+ Registry     Profiles       + Cilium       (ArgoCD)
                                               |
                    +---------------------------+
                    v
         GPU Operator | NIM | Hubble | Tetragon
```

## Prerequisites

- Cisco Intersight account with UCS-X domain
- Red Hat OpenShift subscription (pull secret)
- GitHub Actions self-hosted runner with Docker-in-Docker
- Internal container registry for air-gapped operation
- NVIDIA GPU(s) for AI inference workloads (optional)

## Quick Start

### 1. Configure Secrets

| Secret | Purpose |
|--------|---------|
| `INTERSIGHT_API_KEY_ID` | Intersight API authentication |
| `INTERSIGHT_SECRET_KEY` | Intersight API secret |
| `REDHAT_PULL_SECRET` | Red Hat registry pull secret |
| `SSH_PUBLIC_KEY` | SSH key for cluster node access |

### 2. Customize for Your Environment

Edit `openshift/cluster-mappings.yaml` to define your clusters (IPs, hostnames, storage).

See [Customization Guide](docs/CUSTOMIZATION.md) for detailed instructions.

### 3. Run Workflows

| Phase | Workflow | Description |
|-------|----------|-------------|
| 1 | `ucs-pipeline.yaml` | Validate, deploy, and test UCS server profiles |
| 2 | `openshift-pipeline.yaml` | Install OpenShift with Cilium CNI |

## Hardware Reference

| Cluster | Slot | GPU | Storage | Purpose |
|---------|------|-----|---------|---------|
| ai-pod-1 | 1 | L40S | 1x M.2 | SNO + NVIDIA AI Enterprise |
| ai-pod-2 | 3 | L40S | 1x M.2 | SNO + NVIDIA AI Enterprise |
| ai-pod-3 | 5 | - | 2x M.2 RAID | SNO (compute only) |
| ai-pod-4 | 7 | - | 1x M.2 | SNO (compute only) |

## Directory Structure

```
saif-ai-pod/
├── .github/workflows/       # GitHub Actions automation
│   ├── ucs-pipeline.yaml    # UCS: validate → deploy → test
│   ├── openshift-pipeline.yaml  # OCP: validate → deploy → test
│   └── ...
├── ucs/                     # Cisco Intersight / UCS configuration
│   ├── tf/                  # Terraform code
│   └── config/              # EZI YAML configuration
│       ├── policies/        # BIOS, storage, network policies
│       ├── templates/       # Server profile templates
│       └── profiles/        # Per-server profile assignments
├── openshift/               # OpenShift deployment
│   ├── cluster-mappings.yaml  # Cluster definitions (edit this)
│   ├── templates/           # Jinja2 config templates
│   └── isovalent-manifests/ # Cilium Enterprise manifests
├── manifests/               # Post-install manifests (IDMS, ArgoCD)
├── scripts/                 # Automation scripts
└── docs/                    # Documentation
```

## Documentation

| Document | Purpose |
|----------|---------|
| [Customization Guide](docs/CUSTOMIZATION.md) | Adapting for your environment |
| [Topology](docs/architecture/TOPOLOGY.md) | Infrastructure reference |
| [Method of Procedure](docs/mop/README.md) | Step-by-step deployment |

## Related Repositories

| Repository | Relationship |
|------------|-------------|
| [saif-platform](https://github.com/mahowlin/saif-platform) | Platform orchestration |
| [saif-gitops](https://github.com/mahowlin/saif-gitops) | Day 2 workload management |
| [saif-sys-admin](https://github.com/mahowlin/saif-sys-admin) | Image mirroring, runner VM |

## References

- [Cisco Validated Design - FlexPod MLOps](https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/UCS_CVDs/flexpod_baremetal_mlops_openshift_ai.html)
- [Isovalent Cilium Enterprise](https://docs.isovalent.com/)
- [NVIDIA AI Enterprise on OpenShift](https://docs.nvidia.com/ai-enterprise/)

## License

This project is licensed under the Cisco Sample Code License, Version 1.1. See [LICENSE](LICENSE) for details.
