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
Query Intersight via isctl and generate ucs-state.yaml.

Discovers:
- Chassis info
- Domain profile state
- Server profiles (state, slot, serial)
- MAC addresses (eth0, eth1)
- NVMe drive serial numbers

Usage:
  python scripts/update-ucs-state.py              # Write ucs-state.yaml
  python scripts/update-ucs-state.py --dry-run    # Print to stdout
  python scripts/update-ucs-state.py --output /path/to/file.yaml

Requirements:
  - isctl configured with Intersight credentials
  - INTERSIGHT_API_KEY_ID and INTERSIGHT_SECRET_KEY environment variables
    (or isctl config file)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


def isctl(*args):
    """Run isctl command and return parsed JSON output.

    Args:
        *args: Command arguments to pass to isctl

    Returns:
        Parsed JSON (list or dict), or empty list on error
    """
    cmd = ['isctl'] + list(args) + ['-o', 'json']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        print(f"WARN: isctl timeout: {' '.join(cmd)}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("ERROR: isctl not found in PATH", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        # Don't warn on empty results (expected for some queries)
        if 'no resources found' not in result.stderr.lower():
            print(f"WARN: isctl failed: {result.stderr.strip()}", file=sys.stderr)
        return []

    try:
        data = json.loads(result.stdout)
        # isctl returns a list for 'get' commands
        return data if isinstance(data, list) else [data] if data else []
    except json.JSONDecodeError:
        return []


def map_state(raw_state):
    """Map Intersight ConfigState to simplified state.

    Args:
        raw_state: Raw ConfigState from Intersight API

    Returns:
        Simplified state: 'Deployed', 'Configuring', or 'Unassigned'
    """
    if raw_state == 'Associated':
        return 'Deployed'
    elif raw_state in ('Pending-changes', 'Assigned', 'Validating',
                       'Configuring', 'Activating'):
        return 'Configuring'
    return 'Unassigned'


def get_chassis():
    """Get first chassis name from Intersight.

    Returns:
        Chassis name string, or None if not found
    """
    data = isctl('get', 'equipment', 'chassis', '--top', '1')
    if data:
        return data[0].get('Name')
    return None


def get_domain_profile():
    """Get domain cluster profile name and state.

    Returns:
        Tuple of (name, state), or (None, None) if not found
    """
    data = isctl('get', 'fabric', 'switchclusterprofile', '--top', '1')
    if not data:
        return None, None

    profile = data[0]
    name = profile.get('Name')
    raw_state = profile.get('ConfigContext', {}).get('ConfigState', 'Unassigned')
    state = map_state(raw_state)
    return name, state


def get_nvme_drives():
    """Get all NVMe drives grouped by server serial.

    Queries storage physicaldisk with NVME filter and extracts
    server serial from the Dn path.

    Returns:
        Dict mapping server_serial -> list of drive serials (sorted)
    """
    data = isctl('get', 'storage', 'physicaldisk',
                 '--filter', "contains(Pid,'NVME')")

    drives = {}  # server_serial -> [drive_serials]

    for drive in data:
        # Dn format: /redfish/v1/Systems/SERIALNUMBER01/Storage/MRAID/Drives/1
        dn = drive.get('Dn', '')
        parts = dn.split('/')
        if len(parts) >= 5:
            server_serial = parts[4]  # e.g., SERIALNUMBER01
            drive_serial = drive.get('Serial')
            if server_serial and drive_serial:
                if server_serial not in drives:
                    drives[server_serial] = []
                drives[server_serial].append(drive_serial)

    # Sort each server's drives for consistency
    for serial in drives:
        drives[serial] = sorted(drives[serial])

    return drives


def get_blade_info(blade_moid):
    """Get blade slot and serial from Moid.

    Args:
        blade_moid: Moid of the compute blade

    Returns:
        Tuple of (slot_id, serial), or (0, None) if not found
    """
    if not blade_moid:
        return 0, None

    data = isctl('get', 'compute', 'blade', 'moid', blade_moid)
    if data:
        blade = data[0] if isinstance(data, list) else data
        return blade.get('SlotId', 0), blade.get('Serial')
    return 0, None


def get_mac_addresses(profile_moid):
    """Get MAC addresses for eth0 and eth1 interfaces.

    Args:
        profile_moid: Moid of the server profile

    Returns:
        Tuple of (mac_eth0, mac_eth1), with None for missing MACs
    """
    mac_eth0 = None
    mac_eth1 = None

    if not profile_moid:
        return mac_eth0, mac_eth1

    # Get eth0 MAC
    eth0_data = isctl('get', 'vnic', 'ethif', '--filter',
                      f"Profile.Moid eq '{profile_moid}' and Name eq 'eth0'")
    if eth0_data:
        mac_eth0 = eth0_data[0].get('MacAddress')

    # Get eth1 MAC
    eth1_data = isctl('get', 'vnic', 'ethif', '--filter',
                      f"Profile.Moid eq '{profile_moid}' and Name eq 'eth1'")
    if eth1_data:
        mac_eth1 = eth1_data[0].get('MacAddress')

    return mac_eth0, mac_eth1


def get_server_profiles(nvme_map):
    """Get all server profiles with full state information.

    Args:
        nvme_map: Dict mapping server_serial -> [nvme_serials]

    Returns:
        List of profile dicts with keys:
        - name, slot, serial, state, mac_eth0, mac_eth1, nvme_serials
    """
    profiles = []

    for i in range(1, 5):
        name = f'saif-ai-pod-{i}'
        data = isctl('get', 'server', 'profile', '--filter', f"Name eq '{name}'")

        if not data:
            print(f"WARN: Profile {name} not found", file=sys.stderr)
            continue

        profile = data[0]
        moid = profile.get('Moid')
        raw_state = profile.get('ConfigContext', {}).get('ConfigState', 'Unassigned')
        state = map_state(raw_state)

        # Get blade info (slot, serial)
        assigned_server = profile.get('AssignedServer') or {}
        blade_moid = assigned_server.get('Moid')
        slot, server_serial = get_blade_info(blade_moid)

        # Get MACs (only if deployed or configuring)
        mac_eth0, mac_eth1 = None, None
        if state in ('Deployed', 'Configuring') and moid:
            mac_eth0, mac_eth1 = get_mac_addresses(moid)

        # Get NVMe serials from pre-built map
        nvme_serials = []
        if server_serial and server_serial in nvme_map:
            nvme_serials = nvme_map[server_serial]

        profiles.append({
            'name': name,
            'slot': slot,
            'serial': server_serial,
            'state': state,
            'mac_eth0': mac_eth0,
            'mac_eth1': mac_eth1,
            'nvme_serials': nvme_serials,
        })

        # Progress output
        nvme_count = len(nvme_serials)
        mac_status = "✓" if mac_eth0 else "✗"
        nvme_status = f"{nvme_count}" if nvme_count else "✗"
        print(f"  {name}: slot={slot} state={state} mac={mac_status} nvme={nvme_status}")

    return profiles


def generate_yaml(chassis, domain_name, domain_state, profiles):
    """Generate ucs-state.yaml content.

    Args:
        chassis: Chassis name
        domain_name: Domain profile name
        domain_state: Domain profile state
        profiles: List of server profile dicts

    Returns:
        YAML content as string
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f'updated: "{timestamp}"',
        '',
        'chassis:',
        f'  {chassis}:',
        '',
        '    domain:',
        f'      {domain_name}:',
        f'        state: {domain_state}',
        '',
        '    servers:',
    ]

    for p in profiles:
        lines.append(f"      {p['name']}:")
        lines.append(f"        slot: {p['slot']}")
        lines.append(f"        serial: {p['serial'] or 'null'}")
        lines.append(f"        state: {p['state']}")

        # Format MAC addresses (quoted if present, null if not)
        mac0 = f'"{p["mac_eth0"]}"' if p['mac_eth0'] else 'null'
        mac1 = f'"{p["mac_eth1"]}"' if p['mac_eth1'] else 'null'
        lines.append(f'        mac_eth0: {mac0}')
        lines.append(f'        mac_eth1: {mac1}')

        # Add NVMe serials if present
        if p['nvme_serials']:
            lines.append('        nvme_serials:')
            for serial in p['nvme_serials']:
                lines.append(f'          - "{serial}"')

    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='Query Intersight via isctl and generate ucs-state.yaml'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print YAML to stdout instead of writing file'
    )
    parser.add_argument(
        '--output',
        default='ucs-state.yaml',
        help='Output file path (default: ucs-state.yaml)'
    )
    args = parser.parse_args()

    print("Querying Intersight via isctl...")

    # Get chassis
    chassis = get_chassis()
    if not chassis:
        print('ERROR: No chassis found in Intersight', file=sys.stderr)
        sys.exit(1)
    print(f"  Chassis: {chassis}")

    # Get domain profile
    domain_name, domain_state = get_domain_profile()
    if not domain_name:
        print('ERROR: No domain cluster profile found', file=sys.stderr)
        sys.exit(1)
    print(f"  Domain: {domain_name} ({domain_state})")

    # Get NVMe drives (query once, use for all profiles)
    print("  Querying NVMe drives...")
    nvme_map = get_nvme_drives()
    total_drives = sum(len(v) for v in nvme_map.values())
    print(f"  Found {total_drives} NVMe drives across {len(nvme_map)} servers")

    # Get server profiles
    print("  Querying server profiles...")
    profiles = get_server_profiles(nvme_map)

    # Generate YAML
    yaml_content = generate_yaml(chassis, domain_name, domain_state, profiles)

    if args.dry_run:
        print("\n=== ucs-state.yaml (dry-run) ===")
        print(yaml_content)
    else:
        with open(args.output, 'w') as f:
            f.write(yaml_content)
        print(f"\nWrote {args.output}")


if __name__ == '__main__':
    main()
