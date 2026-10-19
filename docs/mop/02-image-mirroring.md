# Image delivery before installation

Compute consumes image access and policy receipts; it does not own mirroring. [Secure AI Airgap's inventory and production guide](https://github.com/mahowlin/secure-ai-airgap/blob/main/docs/mop/01-image-mirroring.md) replaces the older duplicated recipe here.

For connected installation, verify entitlement and direct access to the selected payload and Isovalent archive/images. For mirrored installation, the preceding registry must already contain the matching selected content, trusted CA and private authentication. Datacenter validates the selected image-policy bundles and records their identities in installer metadata.

The [installation journey](04-openshift-installation.md) then validates those receipts and stages their policy manifests before ISO creation. A hosted registry/cache is a later management-cluster service and cannot bootstrap its own management hosts. There is no `mirror/images-list.yaml` or `openshift/cluster-mappings.yaml` ownership in this repository.
