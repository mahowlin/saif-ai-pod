# Compute topology and ownership

The portable topology is three bare-metal OpenShift control-plane/workload servers on a site management network. Each declares two management NICs, a bond policy, a node address and a boot disk. API and ingress VIPs share that network; DNS, time and image sources must be reachable before boot.

[![Site inputs produce an Agent ISO and site boot installs OpenShift with Isovalent CNI.](../diagrams/compute-overview.svg)](../diagrams/compute-overview.svg)

The optional ACI composition adds separate tenant trunk interfaces and direct guest worker peering. Those values come from [Datacenter's network/host contract](https://github.com/mahowlin/secure-ai-datacenter/blob/main/docs/architectures/FABRIC_NETWORK.md), not an assumed lab leaf/FI/chassis inventory. UCS/FI integration needs its own selected profile and uplink attachment.

The former dated deployment inventory and fixed version table are replaced by maintained `platform-release.yaml`, canonical site inputs and observed runtime evidence. [Customization](../CUSTOMIZATION.md) maps inputs to owners; [installation](../mop/04-openshift-installation.md) explains the result at each stage.
