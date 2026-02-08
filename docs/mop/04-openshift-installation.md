# Day 1: OpenShift Installation

## Overview

Deploy Single Node OpenShift using the Agent-Based Installer with **Cilium Enterprise as Day 1 CNI**. The pipeline handles ISO generation, vMedia boot, installation monitoring, and post-install bootstrap (IDMS + ArgoCD).

## Prerequisites

- [03-intersight-configuration.md](03-intersight-configuration.md) completed
- Server profile deployed and associated
- MAC addresses captured in `cluster-macs.yaml`
- Images mirrored to local registry (via `sync-images` in saif-sys-admin)
- DNS records configured and verified

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenShift Pipeline Flow (openshift-pipeline.yaml)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Validate          2. Generate ISO      3. Upload & Boot     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ DNS, Registry│──►│ install-config│──►│  File Server │      │
│  │ Connectivity │    │ + Cilium Day1│    │  + vMedia    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  4. Installation      5. Post-Install      6. Day 2 Handoff    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ OCP installs │──►│ IDMS Bootstrap│──►│   ArgoCD     │      │
│  │ Cilium CNI   │    │ ArgoCD Boot  │    │   Syncs All  │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Automated Deployment (Recommended)

### Full Pipeline

```bash
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-1 \
  -f cni_type=Cilium
```

**Pipeline stages:**
1. **Validate** - Check DNS, registry, UCS profile state
2. **Deploy** - Generate ISO with Cilium manifests, upload, boot server, monitor installation
3. **Post-install** - Apply bootstrap IDMS, install ArgoCD operator, deploy App-of-Apps
4. **Test** - Verify cluster health, operator status

### Pipeline Inputs

| Input | Options | Default | Purpose |
|-------|---------|---------|---------|
| `cluster_name` | ai-pod-1/2/3/4 | Required | Target cluster |
| `cni_type` | Cilium, OVN | Cilium | CNI type (Cilium recommended) |
| `validate` | true/false | true | Run validation stage |
| `deploy` | true/false | true | Run deployment stage |
| `post_install` | true/false | true | Run post-install (IDMS, ArgoCD) |
| `test` | true/false | true | Run tests |
| `force_deploy` | true/false | false | Bypass operational cluster safeguard |

### Re-run Post-Install Only

For existing clusters needing ArgoCD re-bootstrap:

```bash
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-1 \
  -f validate=false \
  -f deploy=false \
  -f post_install=true \
  -f test=true
```

## What the Pipeline Does

### Stage 1: Validate

- Verifies DNS records (api, api-int, *.apps)
- Tests registry connectivity
- Checks UCS profile state (must be Associated)
- Validates cluster-mappings.yaml and cluster-macs.yaml

### Stage 2: Deploy

1. **Render configs** - `render-cluster-config.py` generates install-config.yaml and agent-config.yaml
2. **Generate ISO** - `openshift-install agent create image` with Cilium Day 1 manifests
3. **Upload ISO** - WebDAV PUT to file server
4. **Configure vMedia** - Update UCS vMedia policy via isctl
5. **Power cycle** - Boot server from ISO
6. **Monitor** - Wait for installation complete (~60-90 min)

### Stage 3: Post-Install

1. **Retrieve kubeconfig** - SSH to node, get recovery kubeconfig
2. **Apply bootstrap IDMS** - Minimal mirrors for ArgoCD installation
3. **Install ArgoCD** - GitOps operator subscription
4. **Deploy App-of-Apps** - Points to saif-gitops

### Stage 4: Test

- Verify all cluster operators healthy
- Check node Ready status
- Validate Cilium pods running
- Test API connectivity

## Manual Procedures (Reference Only)

### Render Cluster Configuration

```bash
# Dry run (view output)
python scripts/render-cluster-config.py ai-pod-1 --dry-run

# Render actual configs
python scripts/render-cluster-config.py ai-pod-1 --cilium
```

**Generated files in `openshift/data/ai-pod-1/`:**
- `install-config.yaml` - OpenShift installation configuration
- `agent-config.yaml` - Agent bootstrap configuration

### Key Configuration (install-config.yaml)

```yaml
metadata:
  name: ai-pod-1
baseDomain: example.com

networking:
  networkType: Cilium          # Day 1 Cilium CNI
  clusterNetwork:
    - cidr: 10.128.0.0/14
      hostPrefix: 23
  serviceNetwork:
    - 172.30.0.0/16

imageContentSources:
  - mirrors:
      - registry.example.com:5000/openshift/release-images
    source: quay.io/openshift-release-dev/ocp-release
```

### Monitor Installation Progress

```bash
# Via workflow logs
gh run watch

# Or SSH to runner and monitor directly
ssh ubuntu@10.0.0.10
cd /data/runner-*/saif-ai-pod/saif-ai-pod/workdir-*/

# Watch bootstrap
openshift-install agent wait-for bootstrap-complete --dir=. --log-level=info

# Watch installation complete
openshift-install agent wait-for install-complete --dir=. --log-level=info
```

### Expected Timeline

| Phase | Duration |
|-------|----------|
| ISO generation | ~1 minute (with credential stripping) |
| Bootstrap | ~30 minutes |
| Installation | ~45-60 minutes |
| Post-install | ~10 minutes |
| **Total** | **~90 minutes** |

## Verification

### Automated (via pipeline)

The test stage verifies:
- All 36 cluster operators healthy (insights may be degraded in air-gap)
- Node shows Ready status
- Cilium pods running in `cilium` namespace
- ArgoCD deployed and syncing

### Manual Verification

```bash
# Get kubeconfig (MCP tool recommended)
cluster_status_connect(cluster_name="ai-pod-1")
export KUBECONFIG=<returned_path>

# Check nodes
oc get nodes
# Expected: cluster-1.example.com Ready master

# Check cluster operators
oc get co
# Expected: All operators Available=True

# Check Cilium
oc get pods -n cilium
# Expected: cilium-xxxxx Running on each node

# Check ArgoCD
oc get applications -n openshift-gitops
# Expected: cluster-apps Synced Healthy
```

## Troubleshooting

### ISO Generation Slow (>5 minutes)

**Cause:** Pull secret contains quay.io credentials, causing direct registry access.

**Solution:** Pipeline automatically strips quay.io credentials. If running manually:
```bash
# Strip credentials before ISO generation
STRIPPED_PULL_SECRET=$(echo "$REDHAT_PULL_SECRET" | python3 -c '
import sys, json
ps = json.load(sys.stdin)
for registry in ["quay.io", "registry.redhat.io", "registry.connect.redhat.com"]:
    ps.get("auths", {}).pop(registry, None)
print(json.dumps(ps))
')
```

### Bootstrap Fails

1. Check agent console via KVM in Intersight
2. Verify DNS resolves from server network
3. Verify registry accessible from server
4. Check network configuration in agent-config.yaml

### Installation Hangs

1. Check cluster operator status
2. Review `.openshift_install.log`
3. SSH to server and check journalctl:
   ```bash
   ssh core@10.0.1.101
   sudo journalctl -f
   ```

### vMedia ISO Caching

**CRITICAL:** Server CIMC may cache ISO content. If regenerating ISO:
1. Full power cycle server (not just reboot)
2. Or update vMedia policy to different filename

### ArgoCD Not Syncing

1. Check ArgoCD pods: `oc get pods -n openshift-gitops`
2. Verify GitHub credentials secret exists
3. Check Application status: `oc describe application cluster-apps -n openshift-gitops`

## Post-Deployment

After successful deployment:

1. **ArgoCD syncs automatically** - All Day 2 components deploy via GitOps
2. **GPU Operator** - Installs driver, enables nvidia.com/gpu resources
3. **Tetragon** - Deploys TracingPolicies for security observability
4. **Hubble Timescape** - Flow storage and visualization
5. **Splunk integration** - OTEL collector for metrics

**No manual Day 2 steps required.** ArgoCD manages everything.

## Rollback

### Redeploy Cluster

```bash
# Force redeploy (bypasses operational cluster check)
gh workflow run openshift-pipeline.yaml \
  -f cluster_name=ai-pod-1 \
  -f cni_type=Cilium \
  -f force_deploy=true
```

### Undeploy Cluster

```bash
gh workflow run openshift-undeploy.yaml \
  -f cluster_name=ai-pod-1 \
  -f confirm_destroy=ai-pod-1 \
  -f clean_kubeconfig=true
```

## Next Steps

After deployment completes:
1. Verify ArgoCD UI accessible at `https://openshift-gitops-server-openshift-gitops.apps.cluster-1.example.com`
2. Monitor Day 2 component deployment in ArgoCD
3. Wait for GPU Operator ClusterPolicy to reach "ready" state (~15 min)
4. Verify Hubble Timescape collecting flows

For Day 2 operations, see [saif-gitops](https://github.com/mahowlin/saif-gitops).
