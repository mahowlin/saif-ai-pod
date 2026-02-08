# Phase 0: Runner VM Bootstrap

## Overview

Deploy the GitHub Actions self-hosted runner VM. This VM hosts the container registry, ISO file server, and GitHub Actions runners for automated workflows.

**Note:** This is a one-time bootstrap procedure that must be run from a local workstation with vCenter access.

## Prerequisites

- [00-prerequisites.md](00-prerequisites.md) completed
- Workstation with vCenter network access
- Terraform >= 1.13.0 installed locally
- Ansible >= 2.15 installed locally
- SSH key pair generated

## The Bootstrap Problem

Phase 0 is a chicken-egg problem: we need a self-hosted runner to deploy infrastructure, but the runner doesn't exist yet.

**Solution:** Bootstrap Phase 0 locally from a workstation with vCenter access.

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 0: LOCAL BOOTSTRAP (from workstation with vCenter access)│
│  ─────────────────────────────────────────────────────────────  │
│  terraform apply + ansible-playbook                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASES 0b-3: AUTOMATED (self-hosted runner + container)       │
│  ─────────────────────────────────────────────────────────────  │
│  runs-on: self-hosted                                           │
│  container: ghcr.io/mahowlin/github-actions-container           │
└─────────────────────────────────────────────────────────────────┘
```

## Procedure

### Step 1: Clone Runner VM Repository

```bash
# Clone your organization's runner VM repository
git clone https://github.com/<YOUR_ORG>/<runner-vm-repo>.git
cd <runner-vm-repo>
```

### Step 2: Configure Terraform Variables

```bash
cd tf
cp ../environments/_template/terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your environment values:

```hcl
# vCenter Connection
vsphere_server   = "vcenter.example.com"
vsphere_user     = "administrator@example.com"
vsphere_password = "<VCENTER_PASSWORD>"

# VM Location
vsphere_datacenter = "MYLAB-DC"
vsphere_cluster    = "infra-cluster"
vsphere_datastore  = "infra-datastore"
vsphere_network    = "VM Network"
vsphere_template   = "ubuntu-24.04-template"
vsphere_folder     = "AI-Pod"

# VM Configuration
vm_name         = "saif-github-runner"
vm_hostname     = "saif-github-runner"
vm_domain       = "example.com"
vm_cpu          = 8
vm_memory       = 32768
vm_disk_os_size = 100
vm_disk_data_size = 500

# Network Configuration
vm_ipv4_address = "10.0.0.10"
vm_ipv4_netmask = 23
vm_ipv4_gateway = "10.0.0.1"
vm_dns_servers  = ["10.0.0.53", "10.0.0.54"]
```

### Step 3: Deploy Runner VM

```bash
terraform init
terraform plan -out=tfplan
```

**Expected Output:**
```
Plan: 1 to add, 0 to change, 0 to destroy.
```

```bash
terraform apply tfplan
```

**Expected Output:**
```
Apply complete! Resources: 1 added, 0 changed, 0 destroyed.

Outputs:
runner_vm_ip = "10.0.0.10"
```

**Verification:**
```bash
ping -c 3 10.0.0.10
ssh ubuntu@10.0.0.10 "hostname -f"
# Expected: runner.example.com
```

### Step 4: Configure Runner VM with Ansible

```bash
cd ../ansible
cp ../environments/_template/hosts.ini.example hosts.ini
```

Edit `hosts.ini`:
```ini
[runner]
10.0.0.10 ansible_user=ubuntu

[runner:vars]
ansible_ssh_private_key_file=~/.ssh/id_rsa
```

Get a GitHub runner registration token:
1. Navigate to: https://github.com/mahowlin/saif-ai-pod/settings/actions/runners/new
2. Copy the registration token (valid for 1 hour)

Run the Ansible playbook:
```bash
RUNNER_TOKEN="<REGISTRATION_TOKEN>"

ansible-playbook -i hosts.ini playbooks/configure-runner.yaml \
  --extra-vars "runner_token=${RUNNER_TOKEN}"
```

**Expected Output:**
```
PLAY RECAP ***
10.0.0.10 : ok=28   changed=25   unreachable=0    failed=0
```

### Step 5: Verify Services

SSH to runner VM and verify services:

```bash
ssh ubuntu@10.0.0.10

# Test container registry
curl -s http://localhost:5000/v2/_catalog
# Expected: {"repositories":[]}

# Test web server (ISO hosting)
curl -s -I http://localhost:8080/
# Expected: HTTP/1.1 200 OK

# Test Terraform state backend
curl -s http://localhost:8081/health
# Expected: OK
```

### Step 6: Verify GitHub Runner Registration

Navigate to: https://github.com/mahowlin/saif-ai-pod/settings/actions/runners

**Expected:** `saif-runner-1`, `saif-runner-2`, `saif-runner-3` show as "Idle"

## Services Architecture

After deployment, the runner VM provides:

| Service | Container | Port | Storage | Purpose |
|---------|-----------|------|---------|---------|
| Container Registry | `registry:2` | 5000 | `/data/registry` | Air-gap image mirror |
| Web Server (ISOs) | `nginx` | 8080 | `/data/images` | Agent ISO hosting |
| Terraform State | `nimbolus/terraform-backend` | 8081 | `/data/tfstate` | State persistence |
| GitHub Runners | `myoung34/github-runner` | - | `/data/runner-*` | CI/CD execution |

## Verification

**Checklist:**

- [ ] VM deployed and accessible via SSH
- [ ] Container registry responds at `:5000`
- [ ] Web server responds at `:8080`
- [ ] Terraform backend responds at `:8081`
- [ ] GitHub runners show as "Idle" in repository settings

## Troubleshooting

### SSH Connection Refused

1. Check VM power state in vCenter
2. Verify network connectivity to VLAN 130
3. Check firewall rules allow SSH

### Registry Not Starting

```bash
sudo docker logs registry
sudo docker restart registry
```

### GitHub Runner Not Registering

1. Verify token is valid (expires after 1 hour)
2. Check runner logs: `sudo docker logs runner-1`
3. Regenerate token and re-run Ansible

### Runner Recreation

If runners are in restart loop:

```bash
# Stop and remove broken containers
ssh ubuntu@10.0.0.10 'sudo docker stop runner-1 runner-2 runner-3 && sudo docker rm runner-1 runner-2 runner-3'

# Get fresh token and re-run Ansible
cd <runner-vm-repo>
RUNNER_TOKEN=$(gh api -X POST /orgs/<YOUR_ORG>/actions/runners/registration-token --jq '.token')
ansible-playbook -i environments/example/hosts.ini \
  ansible/playbooks/configure-runner.yaml \
  --extra-vars "runner_token=${RUNNER_TOKEN}" \
  --tags runner
```

## Rollback

To destroy the runner VM:

```bash
cd <runner-vm-repo>/tf
terraform destroy -auto-approve
```

**Warning:** This removes all services including the container registry and mirrored images.

## Next Steps

Continue to [02-image-mirroring.md](02-image-mirroring.md) to populate the container registry.
