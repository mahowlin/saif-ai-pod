#!/usr/bin/env python3
# Copyright (c) 2026 Cisco and/or its affiliates.
#
# This software is licensed to you under the terms of the Cisco Sample
# Code License, Version 1.1 (the "License"). You may obtain a copy of the
# License at
#
#                https://developer.cisco.com/docs/licenses
#
# All use of the material herein must be in accordance with the terms of
# the License. All rights not expressly granted by the License are
# reserved. Unless required by applicable law or agreed to separately in
# writing, software distributed under the License is distributed on an "AS
# IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.

"""
OpenShift cluster config renderer
Reads cluster-mappings.yaml and ucs-state.yaml, renders Jinja2 templates
"""

import os
import sys
import shutil
import base64
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def b64encode_filter(value):
    """Jinja2 filter to base64 encode a string for Ignition data URLs."""
    if isinstance(value, str):
        value = value.encode('utf-8')
    return base64.b64encode(value).decode('ascii')

def load_ucs_state():
    """Load and cache UCS state file.

    Returns:
        Tuple of (state_data dict, error message or None)
    """
    state_file = 'ucs-state.yaml'

    if not os.path.exists(state_file):
        return None, f"UCS state file not found: {state_file} (run ucs-pipeline workflow first)"

    with open(state_file) as f:
        state_data = yaml.safe_load(f)

    if not state_data or 'chassis' not in state_data:
        return None, f"Invalid UCS state file format: {state_file}"

    return state_data, None


def find_server_in_state(state_data, profile_name):
    """Find server data in UCS state by profile name.

    Returns:
        Server dict or None if not found
    """
    if not state_data:
        return None

    for chassis_name, chassis_data in state_data.get('chassis', {}).items():
        servers = chassis_data.get('servers', {})
        if profile_name in servers:
            return servers[profile_name]
    return None


def load_mac_address(profile_name, interface, warnings, state_data=None):
    """Load MAC address from ucs-state.yaml for specified profile and interface"""
    if state_data is None:
        state_data, error = load_ucs_state()
        if error:
            warnings.append(error)
            return ''

    server = find_server_in_state(state_data, profile_name)
    if not server:
        warnings.append(f"Profile {profile_name} not found in UCS state")
        return ''

    mac_field = f'mac_{interface}'
    mac = server.get(mac_field)
    state = server.get('state', 'Unknown')

    if mac and mac != 'null':
        slot = server.get('slot', 'unknown')
        print(f"  ✅ Found {profile_name} (slot: {slot}): {interface}={mac} (state: {state})")
        return mac
    elif state != 'Deployed':
        warnings.append(f"Server {profile_name} not deployed (state: {state}) - no MAC available")
        return ''
    else:
        warnings.append(f"MAC address empty for {profile_name} interface {interface}")
        return ''


def load_nvme_serials(profile_name, warnings, state_data=None):
    """Load NVMe serial numbers from ucs-state.yaml for specified profile.

    Returns:
        List of NVMe serial numbers, or empty list if not found
    """
    if state_data is None:
        state_data, error = load_ucs_state()
        if error:
            warnings.append(error)
            return []

    server = find_server_in_state(state_data, profile_name)
    if not server:
        warnings.append(f"Profile {profile_name} not found in UCS state")
        return []

    nvme_serials = server.get('nvme_serials', [])
    state = server.get('state', 'Unknown')

    if nvme_serials and len(nvme_serials) == 5:
        print(f"  ✅ Found {profile_name}: {len(nvme_serials)} NVMe serials")
        return nvme_serials
    elif nvme_serials:
        warnings.append(f"Expected 5 NVMe serials for {profile_name}, found {len(nvme_serials)}")
        return nvme_serials
    else:
        # NVMe serials are optional - only warn if state suggests they should exist
        if state in ('Deployed', 'Configuring'):
            print(f"  ⚠️  No NVMe serials found for {profile_name} (mdadm will not be configured)")
        return []

def validate_cluster_data(cluster, infrastructure, warnings):
    """Validate required cluster fields and report missing values"""
    # Required cluster fields
    required_cluster_fields = ['name', 'serial', 'ip', 'hostname', 'interface', 'boot_disk_model', 'ucs_profile']
    # Required infrastructure fields
    required_infra_fields = ['base_domain', 'vlan', 'network_cidr', 'gateway', 'dns_servers']

    # Check cluster fields
    for field in required_cluster_fields:
        if field not in cluster or not cluster[field]:
            warnings.append(f"Cluster field '{field}' is missing or empty")

    # Check infrastructure fields
    for field in required_infra_fields:
        if field not in infrastructure or not infrastructure[field]:
            warnings.append(f"Infrastructure field '{field}' is missing or empty")

def generate_mdadm_base64_content(cluster):
    """Generate base64-encoded content for mdadm files.

    Returns dict with base64-encoded file contents ready for Ignition data URLs.
    """
    nvme_serials = cluster.get('nvme_serials', [])
    if len(nvme_serials) != 5:
        return {}

    # Device list content
    nvme_disks = f"""# NVMe devices for RAID10 array - last entry becomes hot spare
# Cluster: {cluster.get('name', 'unknown')}
# Generated from Intersight API serial numbers
# Path format: scsi-SNVMe_Micron_7450_MTFD_<serial> (MRAID presents as SCSI)
/dev/disk/by-id/scsi-SNVMe_Micron_7450_MTFD_{nvme_serials[0]}
/dev/disk/by-id/scsi-SNVMe_Micron_7450_MTFD_{nvme_serials[1]}
/dev/disk/by-id/scsi-SNVMe_Micron_7450_MTFD_{nvme_serials[2]}
/dev/disk/by-id/scsi-SNVMe_Micron_7450_MTFD_{nvme_serials[3]}
/dev/disk/by-id/scsi-SNVMe_Micron_7450_MTFD_{nvme_serials[4]}
"""

    # Create script - static content
    create_script = r'''#!/bin/bash
# mdadm RAID10 array creation script
#
# Handles three scenarios:
# 1. Fresh install - creates new array
# 2. Redeploy with existing array - adopts array, wipes LVM for clean LVMS
# 3. Redeploy after partial failure - cleans up and recreates
#
# Idempotent: safe to run multiple times

set -euo pipefail

MARKER=/var/lib/mdadm/nvme-data.created
FAILURE_MARKER=/var/lib/mdadm/nvme-data.failed
MD_NAME=nvme-data
MD_DEV=/dev/md/$MD_NAME
LIST=/etc/mdadm/nvme-disks.list
WAIT_MAX=180
WAIT_INTERVAL=5

log() { echo "mdadm: $*"; }
err() { echo "mdadm: ERROR - $*" >&2; }

mkdir -p /var/lib/mdadm

# Skip if already completed
if [[ -f "$MARKER" ]]; then
  log "Array already created (marker exists), skipping"
  exit 0
fi

rm -f "$FAILURE_MARKER"

# Load and validate device list
if [[ ! -f "$LIST" ]]; then
  err "Missing $LIST"
  echo "missing-device-list" > "$FAILURE_MARKER"
  exit 1
fi

mapfile -t DEVS < <(grep -Ev '^\s*(#|$)' "$LIST")

if [[ "${#DEVS[@]}" -ne 5 ]]; then
  err "Expected 5 devices in $LIST, found ${#DEVS[@]}"
  echo "invalid-device-count" > "$FAILURE_MARKER"
  exit 1
fi

for dev in "${DEVS[@]}"; do
  if [[ "$dev" == *-part* ]]; then
    err "Refusing partition device: $dev"
    echo "partition-device" > "$FAILURE_MARKER"
    exit 1
  fi
done

# Check for duplicates
declare -A SEEN=()
for dev in "${DEVS[@]}"; do
  if [[ -n "${SEEN[$dev]:-}" ]]; then
    err "Duplicate device: $dev"
    echo "duplicate-device" > "$FAILURE_MARKER"
    exit 1
  fi
  SEEN[$dev]=1
done

# Wait for devices to appear
log "Waiting for ${#DEVS[@]} devices (max ${WAIT_MAX}s)..."
WAIT_ELAPSED=0
while [[ $WAIT_ELAPSED -lt $WAIT_MAX ]]; do
  MISSING=()
  for dev in "${DEVS[@]}"; do
    [[ ! -e "$dev" ]] && MISSING+=("$dev")
  done
  if [[ ${#MISSING[@]} -eq 0 ]]; then
    log "All devices present after ${WAIT_ELAPSED}s"
    break
  fi
  log "Waiting for ${#MISSING[@]} devices... (${WAIT_ELAPSED}s/${WAIT_MAX}s)"
  sleep $WAIT_INTERVAL
  WAIT_ELAPSED=$((WAIT_ELAPSED + WAIT_INTERVAL))
done

# Final device check
MISSING=()
for dev in "${DEVS[@]}"; do
  [[ ! -e "$dev" ]] && MISSING+=("$dev")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  err "Devices not available after ${WAIT_MAX}s:"
  printf '  %s\n' "${MISSING[@]}" >&2
  echo "devices-not-found" > "$FAILURE_MARKER"
  exit 1
fi

# ============================================================================
# SCENARIO: Check if array already exists (from previous deployment)
# ============================================================================
EXISTING_ARRAY=""

# Method 1: Check for array by name symlink (/dev/md/nvme-data)
if [[ -e "$MD_DEV" ]]; then
  EXISTING_ARRAY=$(readlink -f "$MD_DEV" 2>/dev/null || echo "$MD_DEV")
  log "Found array by name symlink: $EXISTING_ARRAY"
fi

# Method 2: Check if ANY of our devices are already in an md array
# This catches arrays with different names or manually created arrays
if [[ -z "$EXISTING_ARRAY" ]]; then
  log "Checking if devices are in any existing md array..."
  for dev in "${DEVS[@]}"; do
    REAL_DEV=$(readlink -f "$dev" 2>/dev/null || echo "$dev")
    BASE_DEV=$(basename "$REAL_DEV")

    # Check /sys/block for md holders
    if [[ -d "/sys/block/$BASE_DEV/holders" ]]; then
      for holder in /sys/block/$BASE_DEV/holders/md*; do
        if [[ -e "$holder" ]]; then
          MD_HOLDER=$(basename "$holder")
          EXISTING_ARRAY="/dev/$MD_HOLDER"
          log "Found device $dev is part of $EXISTING_ARRAY"
          break 2
        fi
      done
    fi
  done
fi

# Method 3: Check mdadm superblocks on devices (catches stopped arrays)
if [[ -z "$EXISTING_ARRAY" ]]; then
  for dev in "${DEVS[@]}"; do
    if /usr/sbin/mdadm --examine "$dev" &>/dev/null; then
      # Device has md superblock - try to find or assemble the array
      log "Device $dev has mdadm superblock, scanning..."
      /usr/sbin/mdadm --assemble --scan 2>/dev/null || true
      sleep 1
      # Re-check for array
      if [[ -e "$MD_DEV" ]]; then
        EXISTING_ARRAY=$(readlink -f "$MD_DEV" 2>/dev/null || echo "$MD_DEV")
        log "Assembled existing array: $EXISTING_ARRAY"
      fi
      break
    fi
  done
fi

if [[ -n "$EXISTING_ARRAY" ]]; then
  log "Found existing array: $EXISTING_ARRAY"

  # Verify array is healthy (has active devices)
  if /usr/sbin/mdadm --detail "$EXISTING_ARRAY" &>/dev/null; then
    RAID_LEVEL=$(/usr/sbin/mdadm --detail "$EXISTING_ARRAY" | grep "Raid Level" | awk '{print $4}')
    STATE=$(/usr/sbin/mdadm --detail "$EXISTING_ARRAY" | grep "State :" | awk '{print $3}')
    NUM_DEVS=$(/usr/sbin/mdadm --detail "$EXISTING_ARRAY" | grep "Raid Devices" | awk '{print $4}')

    log "Existing array: level=$RAID_LEVEL state=$STATE devices=$NUM_DEVS"

    # Accept healthy RAID10 with 4 devices (our expected config)
    if [[ "$RAID_LEVEL" == "raid10" && "$STATE" =~ ^(clean|active) && "$NUM_DEVS" == "4" ]]; then
      log "Array is healthy RAID10 with expected config, adopting for LVMS"

      # Wipe any existing LVM/filesystem signatures for clean LVMS
      log "Wiping LVM/filesystem signatures for clean LVMS initialization"

      # Dynamically detect VG name on the md device (LVMS creates VG named after LVMVolumeGroup CR)
      # Note: RHEL 9 LVM devices filter may cause pvs to fail with exit 5 - handle gracefully
      VG_ON_MD=$(/usr/sbin/pvs --noheadings -o vg_name "$EXISTING_ARRAY" 2>/dev/null | tr -d ' ' || echo "")
      if [[ -n "$VG_ON_MD" ]]; then
        log "Removing existing VG: $VG_ON_MD"
        /usr/sbin/vgremove -ff -y "$VG_ON_MD" 2>/dev/null || true
      fi
      /usr/sbin/pvremove -ff -y "$EXISTING_ARRAY" 2>/dev/null || true
      /usr/sbin/wipefs -a "$EXISTING_ARRAY" 2>/dev/null || true

      # RHEL 9 CoreOS: Register device with LVM so vg-manager can discover it
      # Without this, LVM commands won't see the device (empty /etc/lvm/devices/system.devices)
      log "Registering $EXISTING_ARRAY with LVM devices filter"
      /usr/sbin/lvmdevices --adddev "$EXISTING_ARRAY" 2>/dev/null || true

      # Ensure mdadm.conf exists for subsequent boots
      {
        echo "# mdadm.conf - adopted existing array"
        echo "DEVICE ${DEVS[*]}"
        /usr/sbin/mdadm --detail --scan --verbose "$EXISTING_ARRAY"
      } > /etc/mdadm.conf

      touch "$MARKER"
      log "Adopted existing array at $EXISTING_ARRAY"
      exit 0
    else
      log "Existing array not suitable (level=$RAID_LEVEL state=$STATE devices=$NUM_DEVS), will recreate"
    fi
  fi

  # Array exists but not healthy or wrong config - stop it for recreation
  log "Stopping existing array for recreation"
  /usr/sbin/mdadm --stop "$EXISTING_ARRAY" 2>/dev/null || true
  sleep 1
fi

# ============================================================================
# SCENARIO: Fresh creation or recreation after stopping old array
# ============================================================================

# Stop any other md arrays that might be using our devices
log "Checking for any md arrays using our devices..."
for dev in "${DEVS[@]}"; do
  # Resolve symlink to actual device
  REAL_DEV=$(readlink -f "$dev" 2>/dev/null || echo "$dev")
  BASE_DEV=$(basename "$REAL_DEV")

  # Check if device is part of any md array
  if [[ -f "/sys/block/$BASE_DEV/holders/"* ]] 2>/dev/null; then
    for holder in /sys/block/$BASE_DEV/holders/md*; do
      if [[ -e "$holder" ]]; then
        MD_HOLDER=$(basename "$holder")
        log "Device $dev is in /dev/$MD_HOLDER, stopping..."
        /usr/sbin/mdadm --stop "/dev/$MD_HOLDER" 2>/dev/null || true
      fi
    done
  fi
done

# Small delay for device release
sleep 2

# Zero superblocks and wipe signatures
log "Cleaning devices (zeroing superblocks, wiping signatures)"
for dev in "${DEVS[@]}"; do
  /usr/sbin/mdadm --zero-superblock --force "$dev" 2>/dev/null || true
  /usr/sbin/wipefs -af "$dev" 2>/dev/null || true
done

# Create the array
log "Creating RAID10 array with 4 data drives + 1 hot spare"
log "Devices: ${DEVS[*]}"

if ! /usr/sbin/mdadm --create "$MD_DEV" \
  --level=10 \
  --raid-devices=4 \
  --spare-devices=1 \
  --metadata=1.2 \
  --chunk=512K \
  --name="$MD_NAME" \
  --homehost=any \
  --bitmap=internal \
  --run \
  "${DEVS[@]}"; then
  err "Array creation failed"
  echo "array-creation-failed" > "$FAILURE_MARKER"
  exit 1
fi

# RHEL 9 CoreOS: Register the new array with LVM devices filter
# Without this, vg-manager can't discover the device for LVMS provisioning
# The device file is empty by default on CoreOS, blocking all LVM discovery
MD_REAL=$(readlink -f "$MD_DEV" 2>/dev/null || echo "$MD_DEV")
log "Registering $MD_REAL with LVM devices filter"
/usr/sbin/lvmdevices --adddev "$MD_REAL" 2>/dev/null || true

# Write mdadm.conf for auto-assembly on subsequent boots
{
  echo "# mdadm.conf - generated by mdadm-create-nvme.sh"
  echo "DEVICE ${DEVS[*]}"
  /usr/sbin/mdadm --detail --scan --verbose
} > /etc/mdadm.conf

touch "$MARKER"
log "RAID10 array created successfully at $MD_DEV"
'''

    # Assemble script - static content
    assemble_script = r'''#!/bin/bash
# Fallback assembly script - runs if udev auto-assembly didn't happen

MD_DEV=/dev/md/nvme-data

if [[ -e "$MD_DEV" ]] || grep -q 'nvme-data' /proc/mdstat 2>/dev/null; then
  echo "mdadm-assemble: Array already active, skipping"
  exit 0
fi

if [[ ! -f /etc/mdadm.conf ]]; then
  echo "mdadm-assemble: No /etc/mdadm.conf, array not yet created"
  exit 0
fi

echo "mdadm-assemble: Attempting fallback assembly..."
/usr/sbin/mdadm --assemble --scan --verbose

if [[ -e "$MD_DEV" ]] || grep -q 'nvme-data' /proc/mdstat 2>/dev/null; then
  echo "mdadm-assemble: Array assembled successfully"
else
  echo "mdadm-assemble: Assembly did not produce array (may need create)"
fi
'''

    return {
        'nvme_disks_b64': base64.b64encode(nvme_disks.encode()).decode(),
        'create_script_b64': base64.b64encode(create_script.encode()).decode(),
        'assemble_script_b64': base64.b64encode(assemble_script.encode()).decode(),
    }


def render_day1_manifests(cluster_name, context, output_dir):
    """Render Day 1 manifests (OperatorHub, CatalogSources) from Jinja2 templates"""
    template_dir = Path("openshift/templates/manifests")
    manifests_dir = Path(output_dir) / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    if not template_dir.exists():
        print(f"  ⚠️  No manifest templates found at {template_dir}")
        return

    # Generate base64-encoded mdadm content
    mdadm_content = generate_mdadm_base64_content(context.get('cluster', {}))
    manifest_context = {**context, **mdadm_content}

    # Setup Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True
    )

    print(f"\n🔧 Rendering Day 1 manifests for {cluster_name}:")

    # Process .j2 template files
    template_files = list(template_dir.glob("*.j2"))
    if not template_files:
        print(f"  ⚠️  No .j2 templates found in {template_dir}")
        return

    for template_file in template_files:
        template = env.get_template(template_file.name)
        rendered = template.render(manifest_context)
        output_file = manifests_dir / template_file.stem  # Remove .j2 extension

        with open(output_file, 'w') as f:
            f.write(rendered)
        print(f"  ✅ {output_file.name}")

    # Copy non-templated manifests (static .yaml files)
    for manifest_file in list(template_dir.glob("*.yaml")) + list(template_dir.glob("*.yml")):
        output_file = manifests_dir / manifest_file.name
        shutil.copy2(manifest_file, output_file)
        print(f"  📋 {output_file.name} (copied)")

    print(f"\n✅ Day 1 manifests rendered to: {manifests_dir}")


def render_cilium_manifests(cluster_name, context, output_dir):
    """Render Cilium manifests from Jinja2 templates"""
    template_dir = Path("openshift/isovalent-manifests")
    manifests_dir = Path(output_dir) / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    # Setup Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True
    )

    print(f"\n🔧 Rendering Cilium manifests for {cluster_name}:")

    # Track which files have .j2 templates (to avoid overwriting with static copies)
    templated_files = set()

    # Process .j2 template files
    for template_file in template_dir.glob("*.j2"):
        template = env.get_template(template_file.name)
        rendered = template.render(context)
        output_file = manifests_dir / template_file.stem  # Remove .j2 extension

        with open(output_file, 'w') as f:
            f.write(rendered)
        print(f"  ✅ {output_file.name}")
        templated_files.add(template_file.stem)  # Track rendered output filename

    # Copy non-templated manifests (skip if .j2 version exists)
    for manifest_file in list(template_dir.glob("*.yaml")) + list(template_dir.glob("*.yml")):
        # Skip if a .j2 template was rendered for this file
        if manifest_file.name in templated_files:
            print(f"  ⏭️  {manifest_file.name} (skipped - .j2 template exists)")
            continue
        output_file = manifests_dir / manifest_file.name
        shutil.copy2(manifest_file, output_file)
        print(f"  📋 {output_file.name} (copied)")

    print(f"\n✅ Cilium manifests rendered to: {manifests_dir}")

def render_cluster(cluster_name, dry_run=False, output_dir=None, inject_secrets=False, cilium=False):
    """Render config for a single cluster"""
    warnings = []

    # Load cluster mappings
    if not os.path.exists('openshift/cluster-mappings.yaml'):
        print(f"❌ cluster-mappings.yaml not found")
        sys.exit(1)

    with open('openshift/cluster-mappings.yaml') as f:
        data = yaml.safe_load(f)

    if not data or 'clusters' not in data:
        print(f"❌ Invalid cluster-mappings.yaml format")
        sys.exit(1)

    # Find cluster
    cluster = next((c for c in data['clusters'] if c.get('name') == cluster_name), None)
    if not cluster:
        print(f"❌ Cluster '{cluster_name}' not found in cluster-mappings.yaml")
        available = [c.get('name', 'unnamed') for c in data.get('clusters', [])]
        print(f"   Available clusters: {', '.join(available)}")
        sys.exit(1)

    if not cluster.get('enabled', True):
        print(f"⚠️  Cluster '{cluster_name}' is disabled in cluster-mappings.yaml")
        return

    print(f"Rendering config for {cluster_name}...")

    # Validate cluster and infrastructure data
    infrastructure = data.get('infrastructure', {})
    validate_cluster_data(cluster, infrastructure, warnings)

    # Load UCS state data once (used for MACs and NVMe serials)
    state_data, state_error = load_ucs_state()
    if state_error:
        warnings.append(state_error)

    # Load MAC addresses for both interfaces (bond configuration)
    profile_name = cluster.get('ucs_profile', '')
    if profile_name:
        cluster['mac_eth0'] = load_mac_address(profile_name, 'eth0', warnings, state_data)
        cluster['mac_eth1'] = load_mac_address(profile_name, 'eth1', warnings, state_data)
        # Keep mac_address for backwards compatibility (uses eth0)
        cluster['mac_address'] = cluster['mac_eth0']

        # Load NVMe serial numbers for mdadm configuration
        cluster['nvme_serials'] = load_nvme_serials(profile_name, warnings, state_data)
    else:
        warnings.append("Cluster UCS profile name is missing")
        cluster['mac_eth0'] = ''
        cluster['mac_eth1'] = ''
        cluster['mac_address'] = ''
        cluster['nvme_serials'] = []

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader('openshift/templates'))

    context = {
        'cluster': cluster,
        'infrastructure': infrastructure
    }

    # Add secrets to context if inject_secrets flag is set
    if inject_secrets:
        pull_secret = os.environ.get('REDHAT_PULL_SECRET', '')
        ssh_key = os.environ.get('SSH_PUBLIC_KEY', '')
        additional_trust_bundle = os.environ.get('REGISTRY_CA_CERT', '')

        if not pull_secret:
            warnings.append("REDHAT_PULL_SECRET environment variable not set")
        if not ssh_key:
            warnings.append("SSH_PUBLIC_KEY environment variable not set")

        context['pull_secret'] = pull_secret
        context['ssh_key'] = ssh_key
        context['additional_trust_bundle'] = additional_trust_bundle
        print(f"  🔐 Injecting secrets from environment variables")
        if additional_trust_bundle:
            print(f"  🔒 Including registry CA certificate in additionalTrustBundle")

    # Output directory
    if output_dir is None:
        output_dir = f"openshift/data/{cluster_name}"
    os.makedirs(output_dir, exist_ok=True)

    # Render templates
    for template_name in ['install-config.yaml.j2', 'agent-config.yaml.j2']:
        try:
            template = env.get_template(template_name)
            rendered = template.render(context)
            output_file = template_name.replace('.j2', '')

            if dry_run:
                print(f"\n=== {output_file} for {cluster_name} ===")
                print(rendered)
            else:
                with open(f'{output_dir}/{output_file}', 'w') as f:
                    f.write(rendered)
                print(f"✅ Wrote {output_dir}/{output_file}")
        except Exception as e:
            warnings.append(f"Failed to render {template_name}: {str(e)}")

    # Render Day 1 manifests (OperatorHub, CatalogSources)
    if not dry_run:
        try:
            render_day1_manifests(cluster_name, context, Path(output_dir))
        except Exception as e:
            warnings.append(f"Failed to render Day 1 manifests: {str(e)}")

    # Render Cilium manifests (opt-in via --cilium flag for Day 1 CNI)
    if cilium and not dry_run:
        try:
            render_cilium_manifests(cluster_name, context, Path(output_dir))
        except Exception as e:
            warnings.append(f"Failed to render Cilium manifests: {str(e)}")

    # Report warnings
    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
        print(f"\n❌ Rendering completed with warnings. Review and fix the issues above.")
        sys.exit(1)
    else:
        if not dry_run:
            print(f"\n✅ Rendered config for {cluster_name} successfully")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Render OpenShift cluster configs')
    parser.add_argument('cluster', help='Cluster name (ai-pod-1, ai-pod-2, etc.)')
    parser.add_argument('--dry-run', action='store_true', help='Print without writing')
    parser.add_argument('--output-dir', help='Output directory (default: openshift/data/{cluster})')
    parser.add_argument('--inject-secrets', action='store_true',
                        help='Inject secrets from REDHAT_PULL_SECRET and SSH_PUBLIC_KEY environment variables')
    parser.add_argument('--cilium', action='store_true',
                        help='Render Cilium Day 1 manifests for CNI with Kube-Proxy Replacement')
    args = parser.parse_args()

    render_cluster(args.cluster, dry_run=args.dry_run, output_dir=args.output_dir,
                   inject_secrets=args.inject_secrets, cilium=args.cilium)

if __name__ == '__main__':
    main()
