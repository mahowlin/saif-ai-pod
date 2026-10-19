# Troubleshoot by installation stage

Keep installer logs and kubeconfig private. Start with the failed stage and its actual inputs; avoid changing generated configuration or issuing a blanket reinstall.

| Symptom | Inspect first | Correct owner |
|---|---|---|
| Unknown cluster or raw hash mismatch | Selected input root, manifest and pristine Compute target root | Datacenter render/handoff |
| Declared hardware invalid | Real MACs, matching NIC names, boot disk hints and node count | Site cluster inventory |
| CLife/archive mismatch | Payload version, official archive checksum, metadata and enriched manifests | Release selection/private preparation |
| ISO uses stale settings | Fresh installer working directory and actual attached media | Site ISO/media process |
| Bootstrap stalls | Console links/LAG, actual addresses, rendezvous, DNS/time, authenticated image pulls | Site networking/services |
| Cilium unhealthy | Effective CiliumConfig, selected manager/runtime images, pod events and logs | Compute staging, then actual operator reconciliation |
| Post-install fails before API access | Private paths, raw hashes and reviewed GitOps origin/ref/root | Post-install contract |
| Subscription pending | Available catalog/channel and Manual InstallPlan | OpenShift GitOps operator installation |
| Argo CD out of sync | Application conditions, source/ref/path, destination registration, private CA/Secret refs | GitOps source/runtime dependencies |

Use [the exact read-only diagnostic procedure](../../agents/operations.md#read-only-diagnosis). Registry production/host failures belong to [Airgap](https://github.com/mahowlin/secure-ai-airgap/blob/main/docs/mop/04-troubleshooting.md); UCS profile failures belong to [the optional UCS path](03-intersight-configuration.md). Do not weaken TLS, print Secret data or substitute another release to make an input check pass.
