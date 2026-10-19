# Observability after installation

Compute establishes OpenShift and its selected CNI; ongoing telemetry applications are selected through GitOps after the management API is healthy. A local install check does not establish Timescape ingestion or other optional telemetry.

[GitOps observability architecture](https://github.com/mahowlin/secure-ai-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md) owns Hubble/Timescape, exporters, storage and selected monitoring integrations. [Datacenter integration ownership](https://github.com/mahowlin/secure-ai-datacenter/blob/main/docs/INTEGRATIONS.md) maps these choices back to maintained inputs.
