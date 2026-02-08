# Troubleshooting Guide

Common issues and solutions for the saif-ai-pod deployment.

## Table of Contents

- [vMedia / ISO Issues](#vmedia--iso-issues)
- [Registry Issues](#registry-issues)
- [DNS Issues](#dns-issues)
- [UCS / Intersight Issues](#ucs--intersight-issues)
- [OpenShift Installation Issues](#openshift-installation-issues)
- [Cilium Issues](#cilium-issues)
- [GPU Issues](#gpu-issues)
- [GitHub Actions Issues](#github-actions-issues)

---

## vMedia / ISO Issues

### Server Boots with Old Configuration

**Symptom:** Server boots with old registry hostname or network config despite uploading new ISO.

**Cause:** Server CIMC caches vMedia ISO content.

**Solution:**
1. Full power cycle server (not just reboot)
2. Or disconnect/reconnect vMedia in Intersight
3. Or change ISO filename (forces cache invalidation)

**Diagnosis:**
```bash
# Compare ignition on server with ISO content
ssh core@<server-ip> 'sudo cat /run/ignition.json' | jq .

# Extract ignition from ISO for comparison
sudo mount -o loop,ro agent.iso /mnt/iso
sudo cp /mnt/iso/images/ignition.img /tmp/ignition.img.gz
sudo gunzip -f /tmp/ignition.img.gz
cd /tmp && sudo cpio -idv < ignition.img
cat config.ign | jq .
```

### vMedia FileLocation Colon Stripped

**Symptom:** `SanitizedFileLocation` shows `10.0.0.108080` instead of `10.0.0.10:8080`.

**Cause:** Intersight strips colons from `FileLocation` field.

**Solution:** Use separate `HostName` and `RemotePath` fields:
```json
{
  "HostName": "10.0.0.10:8080",
  "RemotePath": "/ai-pod-1/agent.iso",
  "RemoteFile": ""
}
```

---

## Registry Issues

### TLS Certificate Errors During Installation

**Symptom:** Agent installer fails with certificate errors connecting to registry.

**Cause:** Missing or incorrect `additionalTrustBundle` in install-config.yaml.

**Solution:** Ensure the CA certificate is correctly configured:

1. Verify `additionalTrustBundlePolicy: Always` is set in install-config.yaml
2. Include the full CA certificate chain in `additionalTrustBundle`
3. Regenerate ISO after updating install-config.yaml

```yaml
# install-config.yaml
additionalTrustBundlePolicy: Always
additionalTrustBundle: |
  -----BEGIN CERTIFICATE-----
  <CA certificate content>
  -----END CERTIFICATE-----
```

### Registry Not Accessible

**Symptom:** `curl http://registry:5000/v2/_catalog` fails.

**Diagnosis:**
```bash
# Check registry container
ssh ubuntu@10.0.0.10 "sudo docker ps | grep registry"
ssh ubuntu@10.0.0.10 "sudo docker logs registry"

# Check port listening
ss -tlnp | grep 5000

# Check firewall
sudo firewall-cmd --list-ports | grep 5000
```

**Solution:**
```bash
# Restart registry
ssh ubuntu@10.0.0.10 "sudo docker restart registry"

# Add firewall rule if needed
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

### Missing Images in Registry

**Symptom:** Pull fails with "manifest unknown" or "not found".

**Solution:** Re-run image mirroring workflow:
```bash
gh workflow run sync-images.yaml -f dry_run=false
```

---

## DNS Issues

### DNS Not Resolving

**Symptom:** `dig api.cluster-1.example.com` returns no results.

**Diagnosis:**
```bash
# Test specific DNS server
dig api.cluster-1.example.com @10.0.0.53 +short

# Check delegation
dig example.com NS @10.0.0.53
```

**Solution:**
1. Create records in Windows AD DNS (10.0.3.2)
2. Required records: `api`, `api-int`, `*.apps`

### Wrong DNS Server in Agent Config

**Symptom:** Server gets IP but can't resolve internal names.

**Solution:** Verify `dns-resolver` in agent-config.yaml:
```yaml
dns-resolver:
  config:
    server:
      - 10.0.0.53
      - 10.0.0.54
```

---

## UCS / Intersight Issues

### 409 Conflict Errors

**Symptom:** Terraform fails with "409 Conflict" on vNIC or EndPointUser.

**Cause:** Resource exists in Intersight but not in Terraform state.

**Solution:**
```bash
# Delete conflicting resource via isctl
isctl delete vnic ethif moid <MOID>

# Re-run terraform
source ~/.intersight/credentials.env && terraform apply
```

### Profile Stuck in Validating

**Symptom:** Server profile shows "Validating" indefinitely.

**Diagnosis:**
1. Check server power state (should be standby)
2. Check Intersight for validation errors
3. Verify all referenced policies exist

**Solution:**
```bash
# Check profile details
isctl get server profile --filter "Name eq 'saif-ai-pod-1'" -o json | jq '.ConfigContext'
```

### Template Changes Not Applying

**Symptom:** Changed template but profile keeps old settings.

**Solution:** Detach and reattach template:
```bash
# Detach template
isctl update server profile moid <PROFILE_MOID> --SrcTemplate 'null'

# Re-associate (via Terraform or workflow)
```

### Cannot Delete Server Profile

**Symptom:** Delete fails because server is associated.

**Solution:** Unassign first, then delete:
```bash
# Unassign
isctl update server profile moid <MOID> --Action 'Unassign'

# Wait for Not-associated state
isctl get server profile moid <MOID> -o json | jq '.ConfigContext.ConfigState'

# Then delete
isctl delete server profile moid <MOID>
```

---

## OpenShift Installation Issues

### Bootstrap Fails

**Symptom:** `wait-for bootstrap-complete` times out.

**Diagnosis:**
1. Check agent console via KVM - look for errors
2. Verify network config (IP, gateway, DNS)
3. Verify registry accessible

```bash
# From runner, check agent progress
openshift-install agent wait-for bootstrap-complete --dir=. --log-level=debug
```

### Installation Hangs at Operators

**Symptom:** Bootstrap completes but installation hangs.

**Diagnosis:**
```bash
export KUBECONFIG=./auth/kubeconfig
oc get co
oc get pods -A | grep -v Running | grep -v Completed
```

**Common causes:**
- Image pull failures (registry connectivity)
- DNS resolution failures
- Resource limits on SNO

### insights Operator Degraded

**Symptom:** `insights` operator shows degraded.

**This is expected** in air-gapped environments. The operator cannot reach console.redhat.com.

### Marketplace Pods Failing

**Symptom:** Pods in `openshift-marketplace` failing.

**Cause:** Not all operator catalogs mirrored.

**Solution:** Either mirror missing catalogs or disable marketplace:
```bash
oc patch operatorhub cluster --type merge -p '{"spec":{"disableAllDefaultSources":true}}'
```

---

## Cilium Issues

### Cilium Pods CrashLooping

**Symptom:** Cilium pods restart repeatedly.

**Diagnosis:**
```bash
oc logs -n cilium ds/cilium -c cilium-agent
```

**Common causes:**
- `k8sServiceHost` DNS not resolving
- Missing `KUBERNETES_SERVICE_HOST` env var
- Incorrect IPAM configuration

**Solution:** Verify CiliumConfig:
```bash
oc get ciliumconfig ciliumconfig -n cilium -o yaml
```

### Kube Proxy Still Running

**Symptom:** kube-proxy pods exist despite KPR enabled.

**Solution:**
```bash
oc patch network.operator cluster --type merge -p '{"spec":{"deployKubeProxy":false}}'
```

### Network Policy Not Working

**Diagnosis:**
```bash
# Check Cilium policy status
oc exec -n cilium ds/cilium -- cilium policy get

# Check endpoint status
oc exec -n cilium ds/cilium -- cilium endpoint list
```

---

## GPU Issues

### No GPU Label on Node

**Symptom:** `oc get nodes -l feature.node.kubernetes.io/pci-10de.present=true` returns nothing.

**Diagnosis:**
```bash
# Check NFD worker logs
oc logs -n openshift-nfd -l app.kubernetes.io/component=worker

# Check lspci on node
ssh core@<node-ip> "lspci | grep -i nvidia"
```

**Solution:** Ensure NFD is running and configured correctly.

### Driver Pod CrashLooping

**Symptom:** nvidia-driver-daemonset pod restarts.

**Diagnosis:**
```bash
oc logs -n nvidia-gpu-operator ds/nvidia-driver-daemonset
```

**Common causes:**
- Secure Boot enabled (must be disabled)
- Kernel version mismatch
- Driver download failure

**Solution:** Verify Secure Boot is disabled in BIOS.

### nvidia-smi Not Working

**Symptom:** `nvidia-smi` command fails or shows no GPU.

**Diagnosis:**
```bash
# Check driver pod
oc get pods -n nvidia-gpu-operator -l app=nvidia-driver-daemonset

# Check ClusterPolicy status
oc get clusterpolicy gpu-cluster-policy -o jsonpath='{.status.state}'
```

---

## GitHub Actions Issues

### Runner Not Picking Up Jobs

**Symptom:** Workflows queue but don't start.

**Diagnosis:**
```bash
# Check runner status
ssh ubuntu@10.0.0.10 "sudo docker ps | grep runner"
ssh ubuntu@10.0.0.10 "sudo docker logs runner-1"
```

**Solution:**
```bash
# Recreate runners
RUNNER_TOKEN=$(gh api -X POST /orgs/mahowlin/actions/runners/registration-token --jq '.token')
ansible-playbook -i hosts.ini playbooks/configure-runner.yaml --extra-vars "runner_token=${RUNNER_TOKEN}" --tags runner
```

### Container Image Pull Failures

**Symptom:** Workflow fails with "image not found".

**Solution:** Verify container tag:
```bash
gh variable list | grep CONTAINER_TAG

# Update if needed
gh variable set CONTAINER_TAG --body "commit-<new-sha>"
```

### Terraform State Lock

**Symptom:** "Error acquiring the state lock".

**Solution:** Force unlock (use cautiously):
```bash
terraform force-unlock <LOCK_ID>
```

---

## General Debugging Commands

### Check Cluster Health

```bash
oc get nodes
oc get co
oc get pods -A | grep -v Running | grep -v Completed
```

### Check Events

```bash
oc get events -A --sort-by='.lastTimestamp' | tail -20
```

### Pod Logs

```bash
oc logs <pod-name> -n <namespace>
oc logs <pod-name> -n <namespace> --previous  # Previous container
```

### Describe Resources

```bash
oc describe pod <pod-name> -n <namespace>
oc describe node <node-name>
```

### SSH to Node

```bash
ssh core@<node-ip>
sudo journalctl -f
sudo crictl ps
```
