# Local inspection and site adapters

## Declared inventory without an API

Set up the environment in [AGENTS](../AGENTS.md). This copies a synthetic example into a temporary directory and validates its declared hardware, not a real server. It makes no hardware API call.

```bash
COMPUTE_ROOT="$PWD"
COMPUTE_PYTHON="$COMPUTE_ROOT/.venv/bin/python"
INSTALL_CHECK="$(mktemp -d)/example-third-party"
mkdir -p "$INSTALL_CHECK"
cp -rf data/openshift/example-third-party/. "$INSTALL_CHECK/"
"$COMPUTE_PYTHON" scripts/resolve-agent-hardware.py \
  --cluster-dir "$INSTALL_CHECK" --inventory-source declared
```

## Optional site workflows

The executable contracts are the actual files, not former `cluster-mappings.yaml` or `mirror/images-list.yaml` recipes:

- [`ucs-pipeline.yaml`](../.github/workflows/ucs-pipeline.yaml): `operation`, explicit `server_target`, `domain_state`, validation/test switches and destructive-operation confirmation. Plan previews; Stage writes Intersight configuration; Activate writes server state. Existing profile choices are site-specific.
- [`openshift-pipeline.yaml`](../.github/workflows/openshift-pipeline.yaml): `cluster_name`, `cni_type`, stage booleans and `post_install_contract` JSON. Deploy writes selected hardware/disks and requires site support; it is not the generic third-party BMC interface.
- [`openshift-post-install.yaml`](../.github/workflows/openshift-post-install.yaml): separate `cluster_dir`, `artifact_manifest`, `raw_target_root`, `gitops_target_root`; all must already exist in the configured runner. [Post-install semantics](../docs/POST_INSTALL.md) describe catalog/Manual InstallPlan/trust behavior.

Configure `RUNNER_LABELS`, `RUNNER_CONTAINER_IMAGE` and selected private credentials through the site's normal runtime process. Two legacy provenance paths also require `RUNNER_CONTAINER_IMAGE`; it does not select the runner image. Runner setup and image production are owned by Airgap. Do not dispatch the live adapters to prove local syntax.

For the post-install local contract check, use an already prepared install and clean reviewed GitOps checkout. This validates local identity/paths, not cluster availability:

```bash
: "${INSTALL_WORK:?Set prepared private install directory}"
: "${MANIFEST:?Set pristine artifact manifest path}"
: "${RAW_ROOT:?Set pristine Compute target root}"
: "${GITOPS_ROOT:?Set clean reviewed GitOps checkout}"
.venv/bin/python scripts/validate-selected-cluster-contract.py \
  --cluster-dir "$INSTALL_WORK" --action post-install \
  --artifact-manifest "$MANIFEST" --raw-target-root "$RAW_ROOT" \
  --gitops-target-root "$GITOPS_ROOT"
```

## UCS plan invocation

After the site configures the existing runner and actual target profile, this invokes the existing Plan operation. It contacts site systems through the pipeline; it does not activate hardware. Use a real choice from the workflow, not an arbitrary serial.

```bash
: "${COMPUTE_REPOSITORY:?Set the actual Compute repository}"
: "${REVIEWED_BRANCH:?Set the reviewed source ref}"
: "${SERVER_TARGET:?Set an actual configured server_target choice}"
gh workflow run ucs-pipeline.yaml --repo "$COMPUTE_REPOSITORY" \
  --ref "$REVIEWED_BRANCH" -f operation='Plan - Preview config changes' \
  -f server_target="$SERVER_TARGET"
```

Stage/Activate and OpenShift deployment have the effects listed above; supply their actual workflow inputs in the owning site process. The portable Agent installation has its complete separate sequence in [installation](installation.md).

## Read-only diagnosis

Select the intended private kubeconfig; never print it. Installation completion/status commands are maintained once in [installation](installation.md#5-observe-bootstrap-and-installed-readiness). Additional checks:

```bash
: "${KUBECONFIG:?Set intended private cluster kubeconfig}"
oc config current-context
oc get events -A --field-selector type=Warning
oc -n openshift-gitops get applications
oc -n openshift-gitops get subscriptions,installplans
```

For a failed pod, inspect its describe/log output within private operational handling; logs may include site-sensitive data. Before the API exists, use the site's console and installer logs. Do not patch generated intent or clear state as a generic fix.


## Installation and removal adapter boundaries

The automated UCS installation adapter is for mirrored delivery. Connected
Agent Installer delivery remains the independent installation procedure; it is
not implemented by the mirrored UCS deployment job. `openshift-deploy.yaml`
accepts only DEPLOY or DRY-RUN; removal uses the separately confirmed
`openshift-undeploy.yaml`. Dry-run file checks are not deployment qualification.

UCS profile selection reads target-owned active/inactive YAML inventory. Plan
rejects domain mutations. A failed, missing-state or timed-out unassignment
stops before profile-file removal and Terraform apply. Unknown or duplicate
hardware identity and ambiguous virtual drives require reviewed declared
rootDeviceHints; disk count does not prove a RAID virtual drive exists.

The installation safeguard requires normal SSH host trust in the executor,
`SSH_PRIVATE_KEY` and optional `SSH_PROXY_JUMP`. Failed SSH/sudo/API observation
blocks deployment. A successful privileged read finding no known installation
kubeconfig is limited evidence, not proof that a disk contains no valuable data.
The existing force_deploy option is an explicit destructive operator choice;
never enable it merely to work around an observation failure.

Before the orchestrator deploys with post_install enabled, its JSON contract must
identify existing mounted absolute cluster_dir, artifact_manifest,
raw_target_root and gitops_target_root paths. The owning pipeline must preserve
those private mounts across its selected jobs. This preflight checks presence;
the post-install validator still verifies contents and selected identities.

Kubeconfig producers, test consumers and removal use KUBECONFIG_REPOSITORY and
KUBECONFIG_REF (both are required explicit execution inputs). A supplied kubeconfig_path is
caller-owned and used directly, without cloning or deleting it. Workflow-owned
copies and installation work directories are private and cleaned on normal job
completion/failure after diagnostics. Abrupt runner loss still requires owner
reconciliation. No local source check qualifies remote install, cancellation,
credential access or runtime convergence.


The standalone `scripts/render-cluster-config.py` CLI is retired and exits before rendering or writing. Its module functions, legacy templates and historical archives remain available for reference. Use canonical Datacenter inputs, its renderer and generated artifact manifest, then the selected Compute handoff described in [agents/installation.md](installation.md). Do not hand-edit generated targets or use the historical input layout for a new deployment.
