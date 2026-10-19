# Optional runner and site services

Compute consumes a runner; it does not own registry/runners or provision a mandatory VM for portable installation. Existing site services may be used.

Runner hosting, registry, media/state/object services, their configuration and rollout belong to [Secure AI Airgap](https://github.com/mahowlin/secure-ai-airgap/blob/main/docs/mop/03-runner-vm.md). Follow that repository's procedure instead of the former duplicated Terraform/Ansible steps here.

The retained Compute workflows need explicit runner labels/image, private access to Intersight or cluster APIs when selected, and staged artifact paths. [Workflow execution](../../agents/operations.md#optional-site-workflows) maps those inputs to the actual adapters. Persistent host rollout belongs to the owning pipeline.
