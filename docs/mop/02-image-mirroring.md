# Phase 0b: Image Mirroring

## Overview

Mirror OpenShift, Cilium Enterprise, and operator images to the local registry for air-gapped installation.

## Prerequisites

- [01-runner-vm-bootstrap.md](01-runner-vm-bootstrap.md) completed
- Runner VM deployed with registry accessible
- Red Hat pull secret configured in GitHub secrets

## Procedure

### Step 1: Review Image Configuration

The image list is defined in `mirror/images-list.yaml`:

```yaml
kind: ImageSetConfiguration
apiVersion: mirror.openshift.io/v1alpha2
storageConfig:
  registry:
    imageURL: registry.example.com:5000/mirror/metadata
    skipTLS: false
mirror:
  platform:
    channels:
      - name: stable-4.19
        minVersion: '4.19.21'
        maxVersion: '4.19.21'
  operators:
    - catalog: registry.redhat.io/redhat/certified-operator-index:v4.19
      packages:
        - name: isovalent-cilium-enterprise
          defaultChannel: "1.18"
          channels:
            - name: "1.18"
        - name: gpu-operator-certified
          channels:
            - name: v25.10
    - catalog: registry.redhat.io/redhat/redhat-operator-index:v4.19
      packages:
        - name: nfd
          channels:
            - name: stable
  additionalImages:
    - name: quay.io/isovalent/clife@sha256:bf1953...
```

### Step 2: Trigger Mirroring Workflow

**Via GitHub CLI:**
```bash
gh workflow run sync-images.yaml -f dry_run=false
```

**Via GitHub UI:**
1. Navigate to: Actions → "Sync Images"
2. Click "Run workflow"
3. Set `dry_run: false`
4. Click "Run workflow"

### Step 3: Monitor Progress

```bash
# Watch workflow
gh run watch

# Or monitor logs
gh run view --log
```

**Expected Duration:**
- First run: 2-4 hours (downloads ~25GB)
- Subsequent runs: 30-60 minutes (differential updates)

### Step 4: Verify Mirrored Images

After workflow completes:

```bash
# SSH to runner and check registry
ssh ubuntu@10.0.0.10

# List all repositories
curl -s http://localhost:5000/v2/_catalog | jq .

# Check OpenShift release images
curl -s http://localhost:5000/v2/openshift/release-images/tags/list | jq .

# Check Cilium operator
curl -s http://localhost:5000/v2/isovalent/clife/tags/list | jq .

# Check GPU operator index
curl -s http://localhost:5000/v2/nvidia/gpu-operator-certified/tags/list | jq .
```

**Expected repositories include:**
- `openshift/release-images` - OpenShift release
- `openshift/release` - OpenShift components
- `redhat/certified-operator-index` - Certified operators
- `redhat/redhat-operator-index` - Red Hat operators
- `isovalent/*` - Cilium Enterprise images

## Verification

**Checklist:**

- [ ] `openshift/release-images:4.19.21-x86_64` present
- [ ] `redhat-operator-index` present (for NFD)
- [ ] `certified-operator-index` present (for CLIFE, GPU Operator)
- [ ] CLIFE image present (`isovalent/clife`)
- [ ] Registry accessible from target network

**If operators missing:** Re-run workflow after correcting `mirror/images-list.yaml`.

## Common Issues

### oc-mirror Errors

The workflow uses oc-mirror v2. Check for these error patterns:

```bash
# View workflow logs
gh run view --log | grep -i error

# Common issues:
# - "[ERROR]" messages indicate failures
# - "failed to be mirrored" indicates specific image issues
```

### Channel/Version Issues

If oc-mirror fails with channel errors:

1. Verify channel exists in catalog: `oc-mirror list operators --catalog registry.redhat.io/redhat/certified-operator-index:v4.19`
2. Add `defaultChannel` if missing from config
3. Use exact version tags, not ranges

### Bandwidth Saturation

Reduce parallelism if network issues:

Edit workflow to use:
```yaml
--parallel-images 2 --parallel-layers 3
```

Instead of default:
```yaml
--parallel-images 4 --parallel-layers 5
```

### Image Timeout

For large images (>1GB), increase timeout:

```yaml
--image-timeout 30m
```

## Adding New Images

To mirror additional images:

1. Edit `mirror/images-list.yaml`:
   ```yaml
   additionalImages:
     - name: quay.io/your-org/your-image:tag
   ```

2. Commit and push
3. Re-run `sync-images.yaml` workflow

## Updating OpenShift Version

1. Edit `mirror/images-list.yaml`:
   ```yaml
   mirror:
     platform:
       channels:
         - name: stable-4.20
           minVersion: '4.20.0'
           maxVersion: '4.20.0'
   ```

2. Update `openshift/cluster-mappings.yaml` with new version
3. Run `sync-images.yaml` workflow
4. Re-render cluster configs

## Troubleshooting

### Registry Space Issues

Check available space:
```bash
ssh ubuntu@10.0.0.10 "df -h /data"
```

If running low, consider:
- Pruning old images
- Adding storage to `/data` volume

### Authentication Failures

Verify pull secret:
```bash
# Test Red Hat registry access
podman login registry.redhat.io --username <user>

# Test GitHub container registry
podman login ghcr.io --username <user>
```

### Partial Failures

Re-run workflow - oc-mirror handles differential updates and skips already-mirrored images.

## Next Steps

Continue to [03-intersight-configuration.md](03-intersight-configuration.md) to deploy UCS server profiles.
