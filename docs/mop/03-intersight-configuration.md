# Phase 1: Intersight Configuration

## Overview

Deploy UCS server profiles using the easy-imm (Easy Intersight Managed Mode) framework via Terraform. This configures BIOS, storage, network, and boot policies for the UCS-X blades.

## Prerequisites

- [02-image-mirroring.md](02-image-mirroring.md) completed
- Intersight API credentials configured
- Target server serial numbers known
- DNS records created (validated in prerequisites)

## easy-imm Framework

This project uses easy-imm - a YAML-based configuration framework for Cisco Intersight.

**Configuration Files:**
```
ucs/
├── tf/                          # Terraform code
│   ├── main.tf                  # easy-imm module orchestration
│   ├── locals.tf                # Local variables
│   ├── provider.tf              # Intersight provider config
│   ├── outputs.tf               # MAC address outputs
│   └── variables.tf             # Input variables
└── data/example/                 # Environment-specific data
    ├── global_settings.ezi.yaml # Global Intersight settings
    ├── pools.ezi.yaml           # UUID, MAC, IP pools
    ├── policies/                # BIOS, storage, network policies
    ├── templates/               # Server profile templates
    └── profiles/                # Server profile assignments
```

## Procedure

### Step 1: Review Configuration

**Global Settings** (`global_settings.ezi.yaml`):
```yaml
global_settings:
  intersight_fqdn: intersight.com
  tags:
    - key: "Project"
      value: "SAIF-AI-Pod"
```

**Server Template** (`templates/server.ezi.yaml`):
- Template `saif-ai-pod-template` for servers with RAID M.2
- Template `saif-ai-pod-template-noraid` for single M.2 disk

**Server Profiles** (`profiles/server.ezi.yaml`):
```yaml
default:
  profiles:
    server:
      - name: saif-ai-pod-1
        action: No-op
        attach_template: true
        ucs_server_profile_template: saif-ai-pod-template-noraid
        targets:
          - name: ai-pod-1
            serial_number: SERIALNUMBER04
```

### Step 2: Run Terraform Plan

**Via GitHub Workflow (Recommended):**
```bash
gh workflow run ucs-pipeline.yaml \
  -f operation="Plan - Preview config changes" \
  -f server_target=ALL
```

**Or locally:**
```bash
cd ucs/tf
source ~/.intersight/credentials.env && terraform plan
```

**Expected Output:**
```
Plan: X to add, 0 to change, 0 to destroy.

Outputs:
server_mac_addresses = {
  "saif-ai-pod-1" = {
    "eth0" = "00:00:00:00:00:1A"
    "eth1" = "00:00:00:00:00:1B"
  }
}
```

### Step 3: Stage Configuration (Optional)

Stage creates the profile in Intersight without deploying to hardware:

**Via GitHub Workflow:**
```bash
gh workflow run ucs-pipeline.yaml \
  -f operation="Stage - Create/update config (not deployed)" \
  -f server_target=saif-ai-pod-1
```

Wait for workflow completion (5-10 minutes).

### Step 4: Activate Server Profile

Activate creates the profile AND deploys it to hardware in one step:

```bash
gh workflow run ucs-pipeline.yaml \
  -f operation="Activate - Apply config to server" \
  -f server_target=saif-ai-pod-1
```

**Wait for profile to associate** (2-5 minutes). Profile goes through states:
`Validating` → `Configuring` → `Activating` → `Associated`

### Step 5: Verify Deployment

**Check profile status:**
```bash
# Using isctl (if available)
isctl get server profile --filter "contains(Name, 'saif')" \
  -o custom-columns=NAME:.Name,STATE:.ConfigContext.ConfigState

# Expected:
# NAME              STATE
# saif-ai-pod-1   Associated
```

**Verify in Intersight UI:**
1. Navigate to: Infrastructure Service → Profiles → Server Profiles
2. Verify `saif-ai-pod-1` shows "OK" status
3. Confirm server is associated

### Step 6: Verify MAC Addresses

The workflow automatically captures MAC addresses to `ucs-state.yaml`:

```yaml
servers:
  saif-ai-pod-1:
    slot: 1
    state: Deployed
    mac_eth0: "00:00:00:00:00:1A"
    mac_eth1: "00:00:00:00:00:1B"
```

**Also verify in OpenShift cluster-macs.yaml:**
```bash
cat openshift/cluster-macs.yaml
```

### Step 7: Verify Hardware Configuration

**BIOS Settings:**
1. Navigate to Intersight → Servers → `SERIALNUMBER04` → BIOS
2. Confirm Secure Boot: **Disabled** (required for GPU Operator)

**GPU Detection:**
1. Navigate to Intersight → Servers → `SERIALNUMBER04` → PCI Devices
2. Confirm NVIDIA L40S visible

**Boot Order:**
1. Confirm local disk is primary boot device
2. vMedia (CD) should be available for ISO boot

## Workflow Inputs Reference

| Input | Options | Purpose |
|-------|---------|---------|
| `operation` | Plan, Stage, Activate, Deactivate, Delete | What to do |
| `server_target` | saif-ai-pod-1/2/3/4, ALL | Server profile(s) to manage |
| `domain_state` | Unchanged, Deployed, Unassigned | Domain profile (rarely changed) |
| `skip_validation` | true/false | Skip validation step |
| `skip_test` | true/false | Skip test step |
| `confirm_delete` | profile name or ALL | Required for Delete operation |

## Verification

**Checklist:**

- [ ] Terraform apply completed successfully
- [ ] Server profile shows "Associated" state
- [ ] MAC addresses captured in `ucs-state.yaml`
- [ ] Secure Boot disabled in BIOS
- [ ] GPU detected in PCI inventory
- [ ] Boot order includes local disk

## Troubleshooting

### 409 Conflict Errors

Resources exist in Intersight but not in Terraform state:

```bash
# Delete conflicting vNIC
isctl delete vnic ethif moid <MOID>

# Re-run terraform apply
```

### Profile Stuck in Validating

1. Check server power state (should be standby)
2. Verify all referenced policies exist
3. Check Intersight for validation errors

### Template Changes Not Applying

When changing templates, first detach:
```bash
isctl update server profile moid <PROFILE_MOID> --SrcTemplate 'null'
```

Then re-associate with new template.

### Deleting Server Profiles

Must unassign before deleting:
```bash
# Unassign profile
isctl update server profile moid <MOID> --Action 'Unassign'

# Wait for UnConfiguring → Not-associated
# Then delete
isctl delete server profile moid <MOID>
```

## Rollback

**Deactivate profile (unassign from server, keeps config in Intersight):**
```bash
gh workflow run ucs-pipeline.yaml \
  -f operation="Deactivate - Remove from server (keeps config)" \
  -f server_target=saif-ai-pod-1
```

**Delete profile completely (removes from server AND Intersight):**
```bash
gh workflow run ucs-pipeline.yaml \
  -f operation="Delete - Remove from server AND Intersight" \
  -f server_target=saif-ai-pod-1 \
  -f confirm_delete=saif-ai-pod-1
```

## Next Steps

Continue to [04-openshift-installation.md](04-openshift-installation.md) to install OpenShift.
