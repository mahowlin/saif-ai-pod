# Bootstrap Argo CD after installation

Use this optional stage after OpenShift is healthy. It installs the selected OpenShift GitOps operator and points Argo CD at your reviewed GitOps cluster root. It does not create that root.

## Runner inputs

The minimal third-party starter supplies Day 1 installer artifacts, not a
`clusters/example-third-party` GitOps root. The optional **Post-Install
Configuration** adapter consumes these runner inputs:

| Input | Required source |
|---|---|
| `cluster_name` | Selected canonical cluster name. |
| `cluster_dir` | Absolute path to the private prepared/enriched installation directory, with that cluster name as its basename. Prepare it before dispatch, outside the checkout cleaned by Actions. |
| `artifact_manifest` | Absolute path to the platform's pristine `GeneratedArtifactManifest`; required for connected delivery. |
| `raw_target_root` | Absolute pristine generated compute root containing `data/openshift/<cluster>`; required for connected delivery and separate from the enriched tree. |
| `gitops_target_root` | Absolute root of the clean, reviewed customer GitOps Git checkout on the selected runner. |

The existing `openshift-pipeline.yaml` caller forwards these four paths from its
`post_install_contract` JSON input (keys exactly as above). Direct dispatch and
reusable invocation of `openshift-post-install.yaml` expose them individually.
All paths must already be available inside the configured runner container;
these inputs do not upload artifacts or provision a runner. The original UCS
Day 1 adapter remains site-specific; these post-install changes do not replace it.

Before any cluster access, validation checks raw hashes against the separate
prepared tree and permits only the existing private credential/trust enrichment.
Keep legacy enrichment templates out of the pristine generated tree.
The supplied GitOps checkout must have the declared
`metadata.yaml.platformServices.gitops.repoURL` as origin and its HEAD must match
`targetRevision` resolved in that reviewed checkout. No fetch is performed by
validation; supply a current approved checkout. Its declared
`gitopsBootstrapPath` (currently `clusters/<cluster>`) must contain one tracked,
nonempty Kustomization. The adapter uses that validated path in its Argo
Application. This validates local identity and root structure, not remote
availability, an entire Kustomize build, entitlement or a successful Argo sync.

Missing, changed or conflicting inputs fail before kubeconfig retrieval. Do not
create a dummy root, point this stage at the nonexistent example root, bypass
validation or fabricate mirror receipts. Connected delivery applies no bootstrap
mirror policy. Mirrored delivery additionally requires its real selected
`gitops-bootstrap` receipt. The standalone ISO/bootstrap procedure is separate
and does not require this optional stage. For the standalone path, complete installation and readiness checks before configuring this optional stage.

## Catalog, approval and trust

The catalog is not inferred from connected/mirrored mode or from a catalog name.
`PlatformDefaults.spec.gitops.operatorSubscriptions.openshift-gitops-operator`
owns `channel`, `installPlanApproval`, `source`/`sourceRef`,
`sourceNamespace`/`sourceNamespaceRef` and `namespace`/`namespaceRef`.
Existing `catalogSourceAliases` and `namespaces` resolve the references;
conflicting direct/ref declarations fail. The metadata renderer copies that
resolved Subscription into `platformServices.gitops.operatorSubscription`.
Optional `startingCSV` is retained. Select a real available catalog/channel for
the chosen release; a synthetic test does not qualify its availability.

Post-install validates this selection before kubeconfig/Secret/API steps and
materializes the existing `01-subscription.yaml` template and `selection.env` in
a separate runner temporary directory. The bootstrap consumes those outputs;
its catalog lookup and recovery pod selector use the selected source and
source namespace. The selected catalog must already exist. No catalog is
created by this adapter, and a mirror-policy receipt alone does not create one.
`Manual` approval is never converted to `Automatic`: after creating a pending
Subscription the job stops, asks the authorized operator to review its
InstallPlan, and can be rerun once that plan has been approved externally.

A connected site using upstream registries may omit `spec.registry` and mirror
mappings and select `registryTrustPolicy: public`; declare the actual upstream
`releaseImageRepository`. Its rendered `imageDelivery.registry` is empty and
`platformServices` has no site-registry/trust entries. No dummy registry or CA
is required. This does not remove the need for entitled source pulls. If a site
registry is explicitly selected, its `platformServices.registry` must agree
with `imageDelivery.registry` and its trust policy must be explicit. Only
`additional-ca` performs the existing OpenShift `user-ca-bundle` to Argo TLS
ConfigMap handoff; public trust retains system roots. Mirrored delivery still
requires the selected registry and its actual bootstrap mirror receipt.

## Verify and recover

After the pipeline completes, check the selected Subscription and InstallPlan, then the Argo CD Application’s sync and health status. A valid local checkout establishes the input contract; only a successful reconciliation establishes deployed state.

| Failure | Action |
|---|---|
| Path or hash validation | Supply the pristine render and separately prepared installation tree on the selected runner; regenerate from maintained inputs if hashes differ |
| Catalog unavailable | Check the selected source and namespace in the cluster before retrying |
| Pending Manual InstallPlan | Review and approve through your authorized process, then rerun |
| Git source unavailable or sync failed | Check Argo CD repository access, the reviewed ref/root, and the Application conditions; retain credentials privately |

The site-specific UCS and full Day 2 adapters retain their own prerequisites. Catalog installation, InstallPlan approval and application sync are separate operations.
