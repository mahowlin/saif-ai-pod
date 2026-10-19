# Datacenter to Compute ownership

Secure AI Datacenter owns shared site identity, allocations, hardware intent, selected release and enabled features. Compute consumes its generated artifacts and owns installation mechanics and private enrichment. The shared network contract is [Fabric and host networking](https://github.com/mahowlin/secure-ai-datacenter/blob/main/docs/architectures/FABRIC_NETWORK.md).

## Generated inputs and execution owners

| Artifact | Compute path | Purpose |
|---|---|---|
| Agent/install config and metadata | `data/openshift/<cluster>/` | Exact cluster identity, hosts, network, release and selected delivery contract |
| Cilium/OpenShift network intent | `data/openshift/<cluster>/manifests/` | Canonical Day 1 configuration; official CLife archive supplies its remaining install resources |
| Selected UCS overlays | `data/ucs/` | VLAN/vNIC intent consumed by the optional UCS execution model |

The [current example inventory](../../data/openshift/) contains rendered configuration, not an observed deployment. Management `bond0` carries node/API/bootstrap/default-route access; optional `bond1` tenant subinterfaces/bridges and BGP are driven by canonical network/cluster inputs. Do not inherit the former fixed lab VLAN/FI values from a dated topology page.

## Pristine output versus private prepared files

Keep the generated raw snapshot and artifact manifest intact. Prepare a separate private installation directory for real credentials/trust and selected hardware or official archive enrichment. `resolve-agent-hardware.py` validates declared inventory or uses explicitly selected runtime hardware discovery. `enrich-cilium-day1-manifests.py` prepares the official archive using selected metadata/API intent. `validate-selected-cluster-contract.py` checks hashes, selected delivery receipts and enriched Agent staging before installation.

[Agent installation](../../agents/installation.md) owns the exact sequence; [post-install validation](../../agents/operations.md#optional-site-workflows) owns the separate reviewed GitOps checkout contract. Private enrichment must not be used as evidence of a faulty raw render; unresolved placeholders or incompatible source versions are actual failures to fix at their owner.

## Other repositories

GitOps application resources go to Secure AI GitOps, not this repository. ACI tenant/access YAML goes to Secure AI Fabric. Runner/registry/image production belongs to Secure AI Airgap. Compute does not run Datacenter renderers or supply a generic third-party BMC driver; it supplies the validated Agent handoff and optional configured site adapters.
