# Optional UCS / Intersight integration

This path configures UCS policies/profiles and can automate media boot. Use the portable installation path when your site supplies another BMC or physical-media method.

## Inputs and ownership

Datacenter generates selected VLAN, Ethernet Network Group and LAN-connectivity overlays into `data/ucs/`. Compute maintains the existing `ucs/` execution model, Easy-IMM defaults and workflow adapters. Real serials, profile associations, Intersight credentials and state remain site-owned. Do not reinterpret source example profiles as discovered hardware.

## Stages and effects

| UCS Pipeline operation | Effect |
|---|---|
| Plan | Preview selected configuration; no profile deployment |
| Stage | Create/update Intersight configuration without deploying it to a server |
| Activate | Apply profile configuration to hardware |
| Deactivate | Remove profile from the server, keeping Intersight configuration |
| Delete | Remove profile from both server and Intersight; existing confirmation input applies |

The real workflow has explicit `server_target` choices. Adapting those choices is a site integration task; it is not an automatic generic hardware selector. Validation/test stages remain enabled unless the site's actual procedure says otherwise.

[AGENTS workflow execution](../../agents/operations.md#optional-site-workflows) links the exact workflow inputs and configured runner requirements. After hardware preparation, proceed through [Agent installation](04-openshift-installation.md). The public example does not prove a live profile association, hardware boot or successful deployment.
