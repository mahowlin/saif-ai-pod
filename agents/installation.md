# Generic compact OpenShift installation

This is the compute-side procedure for three bare-metal control-plane/workload nodes and Isovalent Networking for Kubernetes. It consumes the existing platform renderer's output. It does not require UCS/Intersight, ACI, a runner VM, hosted clusters or Day 2 operators. Current declared inventory support is static IPv4 and two management NICs with common interface names; boot uses the site's existing BMC or physical-media process.

## 1. Prepare the input and raw artifact handoff

Follow the platform [standalone inputs and render procedure](https://github.com/mahowlin/secure-ai-datacenter/blob/main/agents/installation.md). Retain its `SITE_ROOT`, `PLATFORM_ROOT`, `PLATFORM_PYTHON`, `CLUSTER`, pristine `RAW_ROOT` and `generated/artifact-manifest.yaml`. The selected example is OpenShift 4.19.21 / Isovalent 1.19.7 using retained digest pins and CLife archive facts. A render-only result is not support, entitlement or installation evidence.

Set `COMPUTE_ROOT` to this checkout, `COMPUTE_PYTHON` to its existing requirements environment, and `INSTALL_WORK` to a **fresh private** directory outside all Git checkouts. Keep raw artifacts unchanged. Registry credentials, SSH key and trusted CA stay in private files.

```bash
COMPUTE_ROOT="$PWD"
COMPUTE_PYTHON="$COMPUTE_ROOT/.venv/bin/python"
INSTALL_WORK="$HOME/secure-ai/install/$CLUSTER"
PULL_SECRET_FILE="$HOME/secure-ai/private/pull-secret.json"
SSH_KEY_FILE="$HOME/.ssh/ocp-install.pub"
REGISTRY_CA_FILE="$HOME/secure-ai/private/registry-ca.pem"
mkdir -p "$INSTALL_WORK"
"$PLATFORM_PYTHON" "$PLATFORM_ROOT/scripts/render-ocp.py" \
  --root "$SITE_ROOT" --cluster "$CLUSTER" --executable --output "$INSTALL_WORK" \
  --pull-secret-file "$PULL_SECRET_FILE" --ssh-key-file "$SSH_KEY_FILE" \
  --registry-ca-file "$REGISTRY_CA_FILE"
```

The example declares `additional-ca`. For declared `registryTrustPolicy: public`, omit `--registry-ca-file`. Never disable TLS or supply a made-up CA. The renderer refuses output inside its input root and writes secret-bearing files mode0600 without printing contents. Keep `SITE_ROOT`, raw output and private install directory outside Git. Verify actual authenticated pulls/trust through the site's approved process; file-shape tests cannot establish that access.

If mirrored delivery was selected, copy the **real selected** `image-policy-bundles/` from the platform's validated import into `$INSTALL_WORK`; retain the matching receipt contract. For connected delivery, no mirror receipt is needed. Do not fabricate one. This procedure builds no optional GitOps/Day 2 resources.

## 2. Obtain the matching installer and official CLife archive

Prerequisites: `oc`, SHA-256 tools, `tar`, the Python requirements above, and authenticated entitlement to the declared sources. Select the exact architecture/payload from the site's verified release inputs/receipt; it must match `metadata.yaml.ocpVersion`. The standalone example's optional mirror uses OpenShift 4.19.21; for direct connected access use the approved upstream payload reference. No example registry is assumed to exist.

```bash
# OCP_RELEASE_IMAGE is the site's exact approved payload (prefer a verified digest).
: "${OCP_RELEASE_IMAGE:?Set the selected payload reference}"
mkdir -p "$INSTALL_WORK/bin"
oc adm release extract --registry-config="$PULL_SECRET_FILE" \
  --command=openshift-install --to="$INSTALL_WORK/bin" "$OCP_RELEASE_IMAGE"
"$INSTALL_WORK/bin/openshift-install" version
```

Require that binary's version to match rendered metadata. Obtain the official CLife archive named by `metadata.yaml.ciliumDay1.manifestArchive.url` through entitled access and independently check its published SHA-256 against the declared checksum. Existing example facts came from `secure-ai-airgap/mirror/releases/clife-1.19.7.yaml`; no download/pull was performed by the public render.

```bash
# Set these from the selected archive and its verified published checksum, never a sample dummy.
: "${CLIFE_ARCHIVE:?Set the downloaded official archive path}"
: "${CLIFE_ARCHIVE_SHA256:?Set its verified SHA-256}"
printf '%s  %s\n' "$CLIFE_ARCHIVE_SHA256" "$CLIFE_ARCHIVE" | shasum -a 256 --check
mkdir -p "$INSTALL_WORK/clife-source"
tar -xzf "$CLIFE_ARCHIVE" -C "$INSTALL_WORK/clife-source"
```

Set `CLIFE_DIR` to the extracted directory containing the actual YAML (account for archive parent directories). Confirm the URL/checksum/release agree with metadata before enrichment. The archive supplies CRDs/RBAC/namespace/Deployment/Subscription; five rendered configuration files are not the complete CNI install. Stop on conflicts instead of fitting the selected pins to a different archive.

## 3. Enrich once, then stage the enriched files

```bash
"$COMPUTE_PYTHON" "$COMPUTE_ROOT/scripts/resolve-agent-hardware.py" \
  --cluster-dir "$INSTALL_WORK" --inventory-source declared
"$COMPUTE_PYTHON" "$COMPUTE_ROOT/scripts/enrich-cilium-day1-manifests.py" \
  --cluster-dir "$INSTALL_WORK" --repo-root "$COMPUTE_ROOT" --bundle-dir "$CLIFE_DIR" --bundle-archive "$CLIFE_ARCHIVE"
```

Declared hardware is validated without an API lookup. The existing CLife helper checks the selected manager image/digest, retains the canonical CiliumConfig and Network objects, and sets `KUBERNETES_SERVICE_HOST/PORT` on the manager Deployment and Subscription from the rendered API endpoint. It replaces those env entries instead of appending duplicates. Without `--bundle-dir`, legacy stored templates are a separate historical path, not this procedure.

For **mirrored** delivery only, stage the validated Day 1 receipt payloads into the prepared directory before copying to the Agent directory. This is the existing deploy workflow's image-policy staging boundary, expressed locally; scope-prefixed filenames avoid collisions. The imported bundles must already have passed the platform receipt check and live mirroring must have been run by the owning pipeline.

```bash
# Only when imageDelivery.mode is mirrored (skip entirely for connected mode).
for SCOPE in ocp-install-core cilium-day1; do
  for POLICY in "$INSTALL_WORK/image-policy-bundles/$SCOPE/manifests/"*.yaml; do
    cp -f "$POLICY" "$INSTALL_WORK/manifests/$SCOPE--${POLICY##*/}"
  done
done
```

Use a fresh `openshift/` directory. Copy **only the enriched `manifests/` outputs**, including the canonical Network/Cilium configuration. Do not copy the raw archive over them or repeat manual `yq` environment editing.

```bash
mkdir -p "$INSTALL_WORK/openshift"
find "$INSTALL_WORK/manifests" -maxdepth 1 -type f \( -name "*.yaml" -o -name "*.yml" \) \
  -exec cp -f {} "$INSTALL_WORK/openshift/" \;
"$COMPUTE_PYTHON" "$COMPUTE_ROOT/scripts/validate-selected-cluster-contract.py" \
  --cluster-dir "$INSTALL_WORK" --action deploy --agent-staging \
  --artifact-manifest "$SITE_ROOT/generated/artifact-manifest.yaml" --raw-target-root "$RAW_ROOT"
```

Connected deploy requires hashes for the pristine raw generated set and unchanged canonical metadata/network intent after enrichment, not a mirror-workflow receipt. Mirrored deploy requires selected actual Day 1 receipts with matching scope, content hash, exact release/images and source coverage. Both check the enriched Cilium/CLife contract; `--agent-staging` rejects a changed, missing or extra YAML in `openshift/`. Validation does not contact a registry or cluster.

Before proceeding inspect the non-secret configuration: three real hosts, rendezvous, root disks, addresses/VIPs, bond policy and MTU, DNS/NTP, Cilium network type, pod/service ranges, API endpoint and `deployKubeProxy: false`. Confirm actual image access and hardware support separately. The staging check also requires each selected mirror payload to match its receipt bytes in the prepared directory; receipt validity alone is insufficient. Do not alter the canonical source bundle.

## 4. Build and boot through the site's authorized process

Make a private backup first: the installer consumes files. Installing writes the selected disks; arrange the site's installation window and confirm disk identities before running:

```bash
"$INSTALL_WORK/bin/openshift-install" agent create image --dir "$INSTALL_WORK" --log-level=info
```

Attach the resulting Agent ISO to all three servers using the site's BMC virtual media or physical-media procedure. Boot it initially, then return boot priority to installed disks and detach media as directed. No generic hardware driver or UCS licence is assumed. Console checks cover actual links/LAG, NIC matching, addresses, DNS/time, image pulls and rendezvous reachability; an ISO build proves none of those.

## 5. Observe bootstrap and installed readiness

```bash
"$INSTALL_WORK/bin/openshift-install" agent wait-for bootstrap-complete --dir "$INSTALL_WORK" --log-level=info
"$INSTALL_WORK/bin/openshift-install" agent wait-for install-complete --dir "$INSTALL_WORK" --log-level=info
export KUBECONFIG="$INSTALL_WORK/auth/kubeconfig"
oc get nodes -o wide
oc get clusteroperators
oc get clusterversion
oc -n cilium get pods -o wide
oc -n cilium get daemonsets,deployments
oc get ciliumconfig ciliumconfig -o yaml
cilium -n cilium status
```

Compare observed versions/images and three Ready nodes to declared intent, and inspect operator availability/degradation after convergence. Cilium Ready is not end-to-end networking or optional HCP/BGP/LB/EGW proof. No ISO build, registry authentication, physical boot, API admission or installed qualification has been performed for this example. Keep installation logs/kubeconfig/credentials private.

Optional features retain their existing source dependencies/limits in platform `docs/INTEGRATIONS.md`. The source workflows are site execution adapters, not an automatic third-party BMC interface. Do not dispatch a live pipeline as an offline validation step.
