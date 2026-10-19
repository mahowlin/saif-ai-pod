# Secure AI Compute: agent entry point

Turn Datacenter installer intent into private installation assets and the selected server boot workflow. See [README](README.md) for the human composition.

## Route the task

| Goal | Authoritative editable input | Procedure | Actual output | Relevant check | Next owner |
|---|---|---|---|---|---|
| Prepare portable installation | Datacenter-generated `data/openshift/<cluster>/`; private enrichment outside Git | [installation](agents/installation.md) | private Agent assets and installation handoff | raw manifest checks / `test_portable_install.py` | site boot/install owner |
| Inspect or select hardware adapter | `scripts/`, `ucs/`, selected inventory and workflow mechanics | [operations](agents/operations.md) | resolved hardware/adapter input | declared hardware checks; selected adapter tests | site pipeline |
| Complete cluster bootstrap | post-install workflow inputs | [post-install contract](docs/POST_INSTALL.md) | observed cluster/bootstrap status | selected pod/CNI/OLM gates | GitOps |

## Toolchain and execution boundary

Use the requirements environment, the exact selected `openshift-install`, `oc`, shell and archive/hash tools. UCS additionally requires the selected runner, Intersight/state/serial inputs and private runtime credentials. Declared-inventory and helper tests make no API calls. ISO generation consumes private files; installation writes disks. New cluster intent belongs in Datacenter; never patch generated intent here. Legacy renderer CLI is retired; use the Datacenter handoff.

Keep exact executable sequences in the linked procedure; update its input/output/check handoff when an interface changes. Record unknown runtime facts as unknown rather than inferring them from local success.
