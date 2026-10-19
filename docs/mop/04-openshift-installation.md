# Install OpenShift with Isovalent on bare metal

This is the portable compute journey: declared Datacenter output becomes a private Agent installation, then an installed three-server cluster. It uses no UCS discovery and assumes no particular BMC vendor. Exact execution is maintained once in [the installation procedure](../../agents/installation.md).

## 1. Prepare the input and raw artifact handoff

[Secure AI Datacenter](https://github.com/mahowlin/secure-ai-datacenter/blob/main/docs/architectures/COMPACT_BAREMETAL_INSTALL.md) owns cluster identity, addresses, host inventory, network settings, release and selected features. Receive its pristine five-file set plus artifact manifest. Keep that raw snapshot separate from the private working directory used by the installer.

## 2. Obtain the matching installer and official CLife archive

Before boot, the site needs working DNS/time/network/image access, real NIC and disk identities, reserved API/apps VIPs, authenticated image entitlement and SSH access material. Extract the installer from the exact selected OpenShift payload and obtain the declared official CLife archive. Version and checksum agreement is required; the rendered Cilium configuration alone is not a complete CNI installation.

Connected delivery uses the selected upstream sources. Mirrored delivery additionally consumes actual matching image-policy bundles produced by Airgap. A private registry requires its declared trust material; public trust does not require an invented CA.

## 3. Enrich once, then stage the enriched files

Compute validates declared hardware locally or uses the explicitly selected runtime inventory adapter. It prepares CLife manifests with the rendered API endpoint and exact selected images, while retaining canonical Cilium/network intent. Private credential/trust enrichment belongs only in the installation tree. The staging check compares that tree to raw hashes and rejects missing, changed or extra Agent YAML. It does not test registry authentication or cluster admission.

## 4. Build and boot through the site's authorized process

The Agent installer consumes the prepared files and creates an ISO. The site's boot process attaches it to the selected servers; installation writes the selected disks. Check actual NIC matching, bond/LAG behavior, addressing, DNS/time/image access and rendezvous reachability at the console. Return boot priority to installed disks and detach media after installation. ISO creation alone proves none of these physical conditions.

Optional [UCS automation](03-intersight-configuration.md) can perform the hardware/profile/media handoff. Its preconfigured runner, profiles, Intersight access and state are additional site dependencies, not portable prerequisites.

## 5. Observe bootstrap and installed readiness

The installer reports bootstrap and installation completion. The resulting cluster should have three Ready nodes, converged cluster operators and the selected CLife/Cilium components. Compare actual versions and configuration with input metadata. End-to-end traffic, HCP, BGP, storage and other optional features need their own checks.

The [same executable procedure](../../agents/installation.md#5-observe-bootstrap-and-installed-readiness) contains the exact read-only checks. No physical install is established by the source example.

## 6. Optional GitOps and ongoing operation

[Post-install](../POST_INSTALL.md) selects the GitOps operator catalog and a real reviewed cluster root. A pending Manual InstallPlan remains a separate operator action; a completed bootstrap is not proof of every child Application's health. Use [troubleshooting](troubleshooting.md) to classify failures by stage and [verification](verification-procedures.md) for completion criteria.
