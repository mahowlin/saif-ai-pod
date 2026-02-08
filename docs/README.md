# Documentation Index

This directory contains all documentation for the saif-ai-pod project, a Cisco Validated Design (CVD) for deploying OpenShift with Cilium Enterprise on UCS-X hardware.

## Quick Navigation

| Document | Purpose | When to Use |
|----------|---------|-------------|
| [TOPOLOGY.md](TOPOLOGY.md) | Infrastructure reference | Look up IPs, VLANs, hardware, DNS records |
| [CUSTOMIZATION.md](CUSTOMIZATION.md) | Adaptation guide | Modify for your environment |
| [mop/README.md](mop/README.md) | Procedure index | Execute deployment procedures |

## Documentation Structure

```
docs/
├── README.md                 # This file - documentation index
├── TOPOLOGY.md               # Infrastructure reference (static)
├── CUSTOMIZATION.md          # Adaptation guide for customers
├── mop/                      # Method of Procedure (step-by-step guides)
│   ├── README.md             # Procedure index and execution flow
│   ├── 00-prerequisites.md   # Day 0: Infrastructure validation
│   ├── 01-runner-vm-bootstrap.md    # Phase 0: Runner VM deployment
│   ├── 02-image-mirroring.md        # Phase 0b: oc-mirror workflow
│   ├── 03-intersight-configuration.md  # Phase 1: UCS profiles
│   ├── 04-openshift-installation.md    # Phase 2: Agent-based installer
│   ├── 05-day2-cilium-migration.md     # Phase 3: OVN to Cilium
│   ├── 06-day2-gpu-operator.md         # Phase 3: GPU operator
│   ├── 07-day2-argocd-gitops.md        # Phase 3: ArgoCD bootstrap
│   ├── troubleshooting.md              # Common issues and solutions
│   └── verification-procedures.md      # Health checks and validation
└── archive/                  # Historical documents
    ├── sessions/             # Session-specific plans
    ├── investigations/       # Technical investigations
    ├── planning/             # Implementation planning
    └── handoffs/             # Historical handoffs
```

## Document Types

### Reference Documents (Static)

- **TOPOLOGY.md** - Infrastructure layout, IP addresses, VLANs, hardware inventory
- **CUSTOMIZATION.md** - How to adapt configurations for different environments

### Procedure Documents (mop/)

Step-by-step procedures organized by deployment phase:

| Phase | Procedure | One-Time | Repeatable |
|-------|-----------|----------|------------|
| Day 0 | Prerequisites validation | - | Yes |
| Phase 0 | Runner VM bootstrap | Yes | - |
| Phase 0b | Image mirroring | - | Yes |
| Phase 1 | Intersight configuration | - | Yes |
| Phase 2 | OpenShift installation | - | Yes |
| Phase 3 | Day 2 operations | - | Yes |

### Archive Documents

Historical documents preserved for reference but no longer actively maintained:

- **sessions/** - Session execution plans from development
- **investigations/** - Technical research and analysis
- **planning/** - Implementation planning documents
- **handoffs/** - Historical session handoffs

## Getting Started

### New Deployment

1. Read [TOPOLOGY.md](TOPOLOGY.md) to understand the infrastructure
2. Follow [CUSTOMIZATION.md](CUSTOMIZATION.md) to adapt for your environment
3. Execute procedures in [mop/README.md](mop/README.md) in order

### Continuing Existing Work

1. Resume from the appropriate procedure in [mop/](mop/)

### Troubleshooting

1. Check [mop/troubleshooting.md](mop/troubleshooting.md) for common issues
2. Review [mop/verification-procedures.md](mop/verification-procedures.md) for health checks

## CVD Publication Notes

This documentation is structured for Cisco Validated Design (CVD) publication:

- **Reproducible procedures** - Each step can be followed by customers
- **Clear verification** - Success criteria after each major step
- **Troubleshooting guidance** - Known issues and resolutions
- **Example values marked** - Lab-specific values clearly identified
- **Official references** - Links to Red Hat and Cisco documentation
