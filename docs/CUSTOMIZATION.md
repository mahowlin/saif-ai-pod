# Customization

For standalone bare metal, start with [the existing generic installation procedure](mop/04-openshift-installation.md). Edit the platform's `examples/standalone` input copy: cluster inventory, management network, defaults and selected release. There is no `openshift/cluster-mappings.yaml` in this implementation.

| Choice | Owner |
|---|---|
| Cluster name, node IP/MAC, boot disks, bond and rendezvous | Platform `data/clusters/<cluster>/cluster.yaml`, declared inventory |
| Subnet, gateway, MTU, VLAN | Platform `data/networks/` |
| DNS, NTP, registry/mirrors and reviewed compatibility | Platform `data/defaults/` |
| Exact payload, Cilium images, CLife archive | Platform `platform-release.yaml`; align optional airgap recipes |
| Pull secret, SSH public key and additional registry CA | Private executable render inputs, never committed |
| Official bundle/API env enrichment and ISO | This repo's existing compute helpers and Agent installer |

Current generic boundary is compact three-node, static IPv4 and two management NICs with common names. Use API/API-int records for the declared API VIP, wildcard apps records for ingress VIP, and actual node/service records. Do not point every record to an arbitrary node or assume a Windows DNS backend. TLS uses normal verification; `additional-ca` needs the trusted site CA and `public` does not.

## Optional UCS / pipeline integration

`ucs/defaults/` and generated `data/ucs/` are the existing UCS policy inputs/overlay boundary. UCS-specific discovery requires an Intersight account, live hardware/profile facts and its secrets. These are not standalone prerequisites. See [Intersight procedure](mop/03-intersight-configuration.md).

Existing workflow files are `.github/workflows/ucs-validate.yaml`, `ucs-pipeline.yaml`, `openshift-validate.yaml`, `openshift-pipeline.yaml` and their deploy/test companions. Their declared `workflow_dispatch` inputs are the contract; there are no workflows named `ucs/pipeline.yaml` or `openshift/pipeline.yaml`. Runner placement/image selection uses configured `RUNNER_LABELS` and `RUNNER_CONTAINER_IMAGE`; two legacy provenance checks still read `CONTAINER_TAG`. Configure a runner and private secrets for the selected adapter before any authorized dispatch. Offline syntax/input checks are not permission to deploy.

For exact offline inventory and staging checks use [agent execution](../agents/operations.md). Use [mirroring](mop/02-image-mirroring.md) only when selecting actual mirrored delivery; pre-existing services or connected upstream access do not require provisioning our runner VM. Review the airgap repo's real ImageSet files/scopes rather than copying obsolete `mirror/images-list.yaml` examples.

The [source integration contract](architecture/SAIF_INTEGRATION.md) distinguishes raw generated artifacts from private enrichment. Optional storage, virtualization, HCP, GPU and fabric integrations each need their own site selection and readiness evidence; the generic Day 1 render does not install them.
