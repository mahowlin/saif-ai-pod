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

"""Resolve live UCS hardware facts into AgentConfig before ISO generation.

This script is intentionally used in the OpenShift validation phase. The user
commits intent with placeholders; validation queries Intersight and writes the
resolved MAC addresses and rootDeviceHints back to data/openshift/<cluster> so
that the generated ISO is transparent and reproducible.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


BOOT_MODEL_HINTS = (
    "micron_5400",
    "mtfd",
    "m.2",
    "m2",
)

DATA_DISK_HINTS = (
    "nvme",
    "7450",
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run_isctl(*args):
    cmd = ["isctl", *args, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        fail(f"isctl failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    if not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"isctl returned invalid JSON for {' '.join(cmd)}: {exc}")
    if isinstance(data, list):
        return data
    return [data] if data else []


def normalize_model(value):
    return str(value).strip().replace(" ", "_")


def profile_data(profile_name):
    data = run_isctl("get", "server", "profile", "--filter", f"Name eq '{profile_name}'")
    if len(data) != 1 or data[0].get("Name") != profile_name:
        fail(f"expected one exact server profile in Intersight: {profile_name}")
    return data[0]


def mac_address(profile_moid, interface):
    data = run_isctl(
        "get",
        "vnic",
        "ethif",
        "--filter",
        f"Profile.Moid eq '{profile_moid}' and Name eq '{interface}'",
    )
    if len(data) != 1 or data[0].get("Name") != interface:
        fail(f"expected one exact {interface} vNIC for profile moid {profile_moid}")
    mac = data[0].get("MacAddress")
    if not mac:
        fail(f"{interface} MAC is empty for profile moid {profile_moid}")
    return mac


def virtual_drive_hint(blade_moid):
    if not blade_moid:
        return None
    drives = run_isctl(
        "get",
        "storage",
        "virtualdrive",
        "--filter",
        f"Ancestors/any(t:t/Moid eq '{blade_moid}')",
    )
    if any(not any(parent.get("Moid") == blade_moid for parent in drive.get("Ancestors", [])) for drive in drives):
        fail("virtual drive ancestry does not identify the assigned server")
    if any(not str(d.get("Model") or "").strip() for d in drives):
        fail("incomplete virtual drive model observation for assigned server")
    candidates = drives
    if not candidates:
        return None
    if len(candidates) != 1:
        fail("ambiguous virtual drives; declare a verified rootDeviceHints identity instead")
    model = normalize_model(candidates[0]["Model"])
    return {
        "hint": {"model": model},
        "source": "storage.virtualdrive",
        "detail": f"model={model}",
    }


def disk_text(disk):
    fields = [
        disk.get("Model"),
        disk.get("Pid"),
        disk.get("Name"),
        disk.get("Dn"),
        disk.get("DriveType"),
    ]
    return " ".join(str(f) for f in fields if f).lower()


def disk_size_gib(disk):
    for key in ("Size", "PhysicalBlockSize"):
        value = disk.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 10**9:
            return number / (1024**3)
        if number > 100:
            return number
    return 0


def physical_disk_score(disk):
    text = disk_text(disk)
    score = 0
    if any(hint in text for hint in BOOT_MODEL_HINTS):
        score += 100
    if any(hint in text for hint in DATA_DISK_HINTS):
        score -= 100
    size_gib = disk_size_gib(disk)
    if 800 <= size_gib <= 1100:
        score += 20
    serial = disk.get("Serial")
    if serial:
        score += 10
    state = str(disk.get("DriveState") or disk.get("OperState") or "").lower()
    if state in ("online", "ok", "operable"):
        score += 5
    return score


def physical_disk_hint(blade_moid, server_serial):
    filters = []
    if blade_moid:
        filters.append(f"Ancestors/any(t:t/Moid eq '{blade_moid}')")


    seen = set()
    disks = []
    for filter_expr in filters:
        for disk in run_isctl("get", "storage", "physicaldisk", "--filter", filter_expr):
            if not any(parent.get("Moid") == blade_moid for parent in disk.get("Ancestors", [])):
                fail("physical disk ancestry does not identify the assigned server")
            if not disk.get("Model") or not (disk.get("Moid") or disk.get("Dn") or disk.get("Serial")):
                fail("incomplete physical disk identity observation for assigned server")
            key = disk.get("Moid") or disk.get("Dn") or disk.get("Serial")
            if key and key not in seen:
                seen.add(key)
                disks.append(disk)

    scored = sorted(
        ((physical_disk_score(d), d) for d in disks),
        key=lambda item: item[0],
        reverse=True,
    )
    viable = [(score, disk) for score, disk in scored if score > 0]
    if not viable:
        return None
    if len(viable) > 1 and viable[0][0] == viable[1][0]:
        tied = [disk for score, disk in viable if score == viable[0][0]]
        names = ", ".join(
            f"{d.get('Model') or d.get('Pid') or d.get('Name')}:{d.get('Serial') or 'no-serial'}"
            for d in tied[:3]
        )
        fail(f"ambiguous boot disk candidates for {server_serial}: {names}")

    disk = viable[0][1]
    serial = disk.get("Serial")
    model = normalize_model(disk.get("Model") or disk.get("Pid") or disk.get("Name") or "")
    if serial:
        return {
            "hint": {"serialNumber": str(serial)},
            "source": "storage.physicaldisk",
            "detail": f"model={model}, serial={serial}",
        }
    if model:
        return {
            "hint": {"model": model},
            "source": "storage.physicaldisk",
            "detail": f"model={model}",
        }
    return None


def boot_disk_hint(profile, server_serial):
    assigned = profile.get("AssignedServer") or {}
    blade_moid = assigned.get("Moid")
    resource = {"compute.Blade": "blade", "compute.RackUnit": "rackunit"}.get(assigned.get("ObjectType"))
    if not blade_moid or not resource or not server_serial:
        fail("runtime disk discovery requires an assigned server and declared serial")
    hardware = run_isctl("get", "compute", resource, "--filter", f"Moid eq '{blade_moid}'")
    if len(hardware) != 1 or hardware[0].get("Moid") != blade_moid or hardware[0].get("Serial") != server_serial:
        fail("assigned server identity does not match declared metadata serial")
    hint = virtual_drive_hint(blade_moid)
    if hint:
        return hint
    hint = physical_disk_hint(blade_moid, server_serial)
    if hint:
        return hint
    fail(f"could not resolve boot disk hint for server serial {server_serial}")


def load_yaml(path):
    with path.open() as handle:
        return yaml.safe_load(handle)


def write_yaml(path, data):
    header = "# Generated by validation from committed intent plus live Intersight hardware facts.\n---\n"
    with path.open("w") as handle:
        handle.write(header)
        yaml.safe_dump(data, handle, sort_keys=False)


def expected_hostname(node, base_domain):
    name = node.get("name")
    if not name:
        return None
    if "." in name:
        return name
    return f"{name}.{base_domain}"


def host_ipv4_addresses(host):
    addresses = []
    for interface in host.get("networkConfig", {}).get("interfaces", []):
        ipv4 = interface.get("ipv4") or {}
        for address in ipv4.get("address") or []:
            ip = address.get("ip")
            if ip:
                addresses.append(ip)
    return addresses


def interface_map(host):
    return {interface.get("name"): interface for interface in host.get("interfaces", []) if interface.get("name")}


def validate_identity_inputs(metadata, install_config, agent_config, *, declared=False):
    nodes = metadata.get("nodes") or []
    hosts = agent_config.get("hosts") or []
    base_domain = install_config.get("baseDomain")
    if not base_domain:
        fail("install-config missing baseDomain; cannot validate AgentConfig host identity")
    if len(nodes) != len(hosts):
        fail(f"node/host count mismatch: metadata={len(nodes)} agent-config={len(hosts)}")

    hosts_by_name = {}
    for host in hosts:
        hostname = host.get("hostname")
        if not hostname:
            fail("AgentConfig host missing hostname")
        if hostname in hosts_by_name:
            fail(f"duplicate AgentConfig hostname: {hostname}")
        hosts_by_name[hostname] = host

    expected_names = []
    for idx, node in enumerate(nodes):
        for field in (("name",) if declared else ("name", "ucsProfile", "serial")):
            if not node.get(field):
                fail(f"metadata node {idx} missing {field}")
        hostname = expected_hostname(node, base_domain)
        expected_names.append(hostname)
        if hostname not in hosts_by_name:
            fail(f"metadata node {node['name']} expected AgentConfig hostname {hostname}, but no matching host exists")
        host = hosts_by_name[hostname]
        host_ips = host_ipv4_addresses(host)
        if not host_ips:
            fail(f"AgentConfig host {hostname} has no static IPv4 address")
        interfaces = interface_map(host)
        selected_nics = tuple(interfaces) if declared else ("eth0", "eth1")
        if declared and (not selected_nics or not host.get("rootDeviceHints")):
            fail(f"AgentConfig host {hostname} requires declared interfaces and rootDeviceHints")
        for nic in selected_nics:
            if nic not in interfaces:
                fail(f"AgentConfig host {hostname} missing install interface {nic}")
            mac = interfaces[nic].get("macAddress")
            if mac and mac == "MAC_PLACEHOLDER" and not declared:
                continue
            if declared and not mac:
                fail(f"AgentConfig host {hostname} interface {nic} requires a declared MAC")
            if mac and not re.match(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$", mac):
                fail(f"AgentConfig host {hostname} interface {nic} has invalid MAC address {mac!r}")

    extra_names = sorted(set(hosts_by_name) - set(expected_names))
    if extra_names:
        fail(f"AgentConfig contains host(s) not present in metadata: {', '.join(extra_names)}")

    rendezvous_ip = agent_config.get("rendezvousIP")
    if nodes and rendezvous_ip:
        if not any(rendezvous_ip in host_ipv4_addresses(host) for host in hosts_by_name.values()):
            fail(f"rendezvousIP {rendezvous_ip} does not belong to a declared metadata node")

    return hosts_by_name


def main():
    parser = argparse.ArgumentParser(description="Resolve AgentConfig hardware placeholders from Intersight")
    parser.add_argument("--cluster")
    parser.add_argument("--cluster-dir", type=Path, help="Selected private or example install directory; no repository copy required")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--inventory-source", choices=["declared", "runtime"], help="Explicit hardware input contract; otherwise read metadata.hardwareInventory")
    args = parser.parse_args()

    if not args.cluster and args.cluster_dir is None:
        parser.error("--cluster or --cluster-dir is required")
    data_dir = args.cluster_dir or (Path("data") / "openshift" / args.cluster)
    selected_name = args.cluster or data_dir.name
    metadata_path = data_dir / "metadata.yaml"
    install_config_path = data_dir / "install-config.yaml"
    agent_config_path = data_dir / "agent-config.yaml"

    if not metadata_path.exists():
        fail(f"metadata not found: {metadata_path}")
    if not install_config_path.exists():
        fail(f"install-config not found: {install_config_path}")
    if not agent_config_path.exists():
        fail(f"AgentConfig not found: {agent_config_path}")

    metadata = load_yaml(metadata_path)
    install_config = load_yaml(install_config_path)
    agent_config = load_yaml(agent_config_path)

    source = args.inventory_source or metadata.get("hardwareInventory")
    if source not in {"declared", "runtime"}:
        fail("metadata.hardwareInventory or --inventory-source must explicitly select declared or runtime")
    if source == "declared":
        validate_identity_inputs(metadata, install_config, agent_config, declared=True)
        serialized = yaml.safe_dump(agent_config)
        if "PLACEHOLDER" in serialized:
            fail("declared AgentConfig still contains an unresolved hardware placeholder")
        print(f"Declared hardware valid for {selected_name}; no UCS/Intersight discovery or inventory rewrite")
        return
    nodes = metadata.get("nodes") or []
    hosts_by_name = validate_identity_inputs(metadata, install_config, agent_config)

    print(f"Resolving hardware facts for {selected_name} ({len(nodes)} hosts)")

    for node in nodes:
        profile_name = node["ucsProfile"]
        server_serial = node["serial"]
        hostname = expected_hostname(node, install_config["baseDomain"])

        profile = profile_data(profile_name)
        profile_moid = profile.get("Moid")
        if not profile_moid:
            fail(f"profile {profile_name} has no Moid")

        mac_eth0 = mac_address(profile_moid, "eth0")
        mac_eth1 = mac_address(profile_moid, "eth1")
        hint = boot_disk_hint(profile, server_serial)

        host = hosts_by_name[hostname]
        host["rootDeviceHints"] = hint["hint"]
        for interface in host.get("interfaces", []):
            if interface.get("name") == "eth0":
                interface["macAddress"] = mac_eth0
            elif interface.get("name") == "eth1":
                interface["macAddress"] = mac_eth1

        print(f"  {hostname} ({profile_name}, serial={server_serial}): eth0={mac_eth0}, eth1={mac_eth1}, boot={hint['source']} {hint['detail']}")

    validate_identity_inputs(metadata, install_config, agent_config)

    rendered = yaml.safe_dump(agent_config, sort_keys=False)
    if re.search(r"MAC_PLACEHOLDER|BOOT_DISK_MODEL_PLACEHOLDER", rendered):
        fail("hardware placeholders remain after resolution")

    if args.write:
        write_yaml(agent_config_path, agent_config)
        print(f"Wrote resolved AgentConfig: {agent_config_path}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
