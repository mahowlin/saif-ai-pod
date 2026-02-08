# Day 0: Prerequisites and Validation

## Overview

Validate all infrastructure requirements before starting deployment. This procedure ensures DNS, credentials, network connectivity, and hardware are properly configured.

## Prerequisites

- Network access to lab VPN
- GitHub repository access with admin permissions
- Intersight account with API key
- Red Hat account for pull secret
- DNS administrative access (Windows AD DNS)

## Procedure

### Step 1: Configure GitHub Secrets

Navigate to: https://github.com/mahowlin/saif-ai-pod/settings/secrets/actions

Configure the following secrets:

| Secret Name | Description | Source |
|-------------|-------------|--------|
| `INTERSIGHT_API_KEY_ID` | Intersight API Key ID | Intersight Console → Settings → API Keys |
| `INTERSIGHT_SECRET_KEY` | Intersight Secret Key (PEM content) | Downloaded SecretKey.txt file |
| `REDHAT_PULL_SECRET` | Red Hat pull secret JSON | console.redhat.com → Downloads → Pull Secret |
| `SSH_PUBLIC_KEY` | SSH public key for node access | Local workstation (`~/.ssh/id_rsa.pub`) |
| `NGC_API_KEY` | NVIDIA NGC API key | ngc.nvidia.com |
| `GITHUB_RUNNER_TOKEN` | Runner registration token | GitHub Settings → Actions → Runners |

**Verification:**
```bash
# Verify secrets are configured (from GitHub CLI)
gh secret list --repo mahowlin/saif-ai-pod
```

### Step 2: Configure GitHub Repository Variables

Navigate to: https://github.com/mahowlin/saif-ai-pod/settings/variables/actions

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `CONTAINER_TAG` | Container image version | `commit-2060f1b` |
| `OCP_REGISTRY_URL` | Container registry URL | `registry.example.com:5000` |
| `OCP_ISO_SERVER_URL` | ISO file server URL | `http://10.0.0.10:8080` |
| `UCS_TFSTATE_URL` | Terraform state backend | `http://10.0.0.10:8081` |

### Step 3: Validate DNS Records

The following DNS records must exist before cluster installation.

**For each cluster (example: ai-pod-1):**

| Record | Type | Value |
|--------|------|-------|
| `api.cluster-1.example.com` | A | `10.0.1.101` |
| `api-int.cluster-1.example.com` | A | `10.0.1.101` |
| `*.apps.cluster-1.example.com` | A | `10.0.1.101` |

**For registry:**

| Record | Type | Value |
|--------|------|-------|
| `registry.example.com` | A | `10.0.0.10` |

**Commands:**
```bash
DNS_SERVER=10.0.0.53

# Test API endpoint
dig api.cluster-1.example.com @${DNS_SERVER} +short
# Expected: 10.0.1.101

# Test internal API endpoint (required for Cilium KPR)
dig api-int.cluster-1.example.com @${DNS_SERVER} +short
# Expected: 10.0.1.101

# Test wildcard DNS
dig test.apps.cluster-1.example.com @${DNS_SERVER} +short
# Expected: 10.0.1.101

# Test registry DNS
dig registry.example.com @${DNS_SERVER} +short
# Expected: 10.0.0.10
```

### Step 4: Validate Intersight Connectivity

```bash
# Test Intersight API access
curl -s -H "Authorization: Intersight-API-Key <API_KEY_ID>" \
  https://intersight.com/api/v1/compute/PhysicalSummaries?$top=1 | head
```

**Expected:** JSON response with server data

### Step 5: Validate Hardware Prerequisites

| Requirement | Value | Notes |
|-------------|-------|-------|
| UCS-X Chassis | 9508 | Fabric Interconnect attached |
| Server Model | UCSX-210C-M7 | With L40S GPU for AI workloads |
| Secure Boot | Disabled | Required for GPU Operator |
| RAM | 128GB+ | For SNO deployment |
| Storage | 500GB+ NVMe | M.2 for RHCOS installation |

**Hardware Variations - M.2 Storage:**

| Server | M.2 Disks | Storage Policy |
|--------|-----------|----------------|
| ai-pod-1 (Slot 1) | 1 | `saif-ucsx-storage-noraid` |
| ai-pod-2 (Slot 3) | 1 | `saif-ucsx-storage-noraid` |
| ai-pod-3 (Slot 5) | 2 | `saif-ucsx-storage` (RAID1) |
| ai-pod-4 (Slot 7) | 1 | `saif-ucsx-storage-noraid` |

### Step 6: Validate Network Connectivity

Test connectivity from a machine on the target network:

```bash
# Test runner VM
ping -c 3 10.0.0.10

# Test registry port
nc -zv 10.0.0.10 5000
# Expected: Connection succeeded

# Test ISO server port
nc -zv 10.0.0.10 8080
# Expected: Connection succeeded
```

## Verification

**Go/No-Go Checklist:**

- [ ] All GitHub secrets configured
- [ ] All GitHub repository variables set
- [ ] DNS records resolve correctly for all clusters
- [ ] Intersight API accessible and returns data
- [ ] Hardware meets requirements
- [ ] Secure Boot disabled on target servers
- [ ] Network connectivity to runner VM confirmed

**If any checkbox fails:** Do NOT proceed. Resolve the issue before continuing.

## Troubleshooting

### DNS Not Resolving

1. Verify DNS server is reachable: `ping 10.0.0.53`
2. Check delegation from lab DNS to AD DNS
3. Contact network team to create records in Windows AD DNS

### Intersight API Fails

1. Verify API key is valid and not expired
2. Check organization permissions in Intersight
3. Ensure API key type is "OpenAPI schema version 2"

### Network Connectivity Issues

1. Verify VPN connection to lab
2. Check firewall rules allow traffic to runner VM
3. Verify VLAN configuration in ACI

## Next Steps

After completing prerequisites validation:
- If runner VM is not deployed: Continue to [01-runner-vm-bootstrap.md](01-runner-vm-bootstrap.md)
- If runner VM exists but no images: Continue to [02-image-mirroring.md](02-image-mirroring.md)
- If images mirrored: Continue to [03-intersight-configuration.md](03-intersight-configuration.md)
