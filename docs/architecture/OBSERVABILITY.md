# Observability Architecture

> **Note:** Observability is a Day 2 concern managed via GitOps.
>
> The authoritative documentation has moved to:
> **[saif-gitops/docs/OBSERVABILITY_ARCHITECTURE.md](https://github.com/mahowlin/saif-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md)**

## Quick Reference

| Component | Purpose | Documentation |
|-----------|---------|---------------|
| Splunk OTEL Collector | Metrics collection | [gitops-applications](https://github.com/mahowlin/saif-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md#splunk-otel-collector) |
| Hubble Timescape | Network flow storage | [gitops-applications](https://github.com/mahowlin/saif-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md#hubble-timescape) |
| Vector | Log forwarding | [gitops-applications](https://github.com/mahowlin/saif-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md#vector-log-collector) |
| DCGM Exporter | GPU metrics | [gitops-applications](https://github.com/mahowlin/saif-gitops/blob/main/docs/OBSERVABILITY_ARCHITECTURE.md#dcgm-gpu-monitoring) |

## Why Day 2?

Observability components (Splunk OTEL, Vector, Hubble Timescape) are deployed via ArgoCD after cluster creation. This keeps Day 1 minimal and allows independent updates to observability stack.

See [Day 0/1/2 Architecture](https://github.com/mahowlin/saif-platform/blob/main/docs/architecture/DAY0_DAY1_DAY2.md) for the full deployment model.
