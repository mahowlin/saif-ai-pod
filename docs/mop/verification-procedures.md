# Installation and handoff verification

Verify the result of each owner before continuing; a local YAML or syntax check is not hardware readiness. Exact commands live in [agent installation](../../agents/installation.md) and [read-only diagnosis](../../agents/operations.md#read-only-diagnosis).

| Stage | Evidence to retain privately | What it does not establish |
|---|---|---|
| Datacenter handoff | Raw files, source identity and matching artifact hashes | Registry access or hardware compatibility |
| Private preparation | Actual NIC/disk identities, official archive checksum, matching release and validated Agent staging | A running cluster |
| Image delivery | Selected source/destination content, auth and trust receipts for mirrored mode | Cold pulls on every host |
| ISO and boot | ISO identity, selected server console and rendezvous/bootstrap logs | Installed operators or application readiness |
| Installed OpenShift | Three Ready nodes, version and converged core operators | Optional storage/HCP/BGP/application operation |
| Isovalent CNI | Selected CLife/Cilium version, healthy components and effective configuration | End-to-end traffic without a traffic test |
| Optional GitOps | Correct catalog/InstallPlan, registered repo/ref/root and Application sync/health | Every child source is rendered or healthy |

For optional runner, registry and UCS stages, use their owning guides rather than the obsolete combined phase checklist. [Post-install](../POST_INSTALL.md) distinguishes input validation from reconciliation.
