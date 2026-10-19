# Prerequisites

## Generic declared-inventory path

Use [OpenShift installation](04-openshift-installation.md) for the full supported input boundary and actual commands. Supply three appropriate bare-metal servers, exact NIC MACs and boot disk hints, static IPv4 addresses, matching bond/LAG policy, API/ingress VIPs, reachable DNS/NTP and entitled image sources. Use your DNS service; Windows AD DNS, a lab VPN, UCS chassis/model and Intersight are not generic requirements.

Install the checkout's Python requirements in its documented environment. The operator workstation needs `oc`, the matching `openshift-install`, `tar` and SHA-256 tools. Private pull secret, SSH public key and trusted registry CA (only with `additional-ca`) stay outside Git. Connected deployments verify raw artifact hashes and official archive metadata; mirrored deployments additionally verify real selected mirror receipts.

## Optional site workflows

Configured GitHub Actions runners need `RUNNER_LABELS` (JSON array) and `RUNNER_CONTAINER_IMAGE`. `CONTAINER_TAG` remains a legacy provenance input in two workflows; it is not the container-image selector. Repository secrets and permissions must match the chosen workflow. Inspect `.github/workflows/` before dispatch; configure the site runner/bootstrap separately.

UCS adapters additionally need Intersight credentials, actual associated profiles/serials and a reachable state backend. GPU, SNO, HCP and Day 2 operators are separate choices, not hardware requirements of the generic compact example. See [Intersight configuration](03-intersight-configuration.md) and [runner bootstrap](01-runner-vm-bootstrap.md) only for those integrations. No example chassis, disk serial, slot assignment, VPN, DNS backend or registry certificate should be inherited as an actual site fact.
