#!/usr/bin/env python3
"""Validate Agent-Based Installer embedded manifests against repo intent."""

import argparse
import json
import re
import shlex
from pathlib import Path

import yaml


MANIFESTS = {
    "cluster-image-set": "cluster-image-set.yaml",
    "agent-cluster-install": "agent-cluster-install.yaml",
    "infraenv": "infraenv.yaml",
    "agent-config": "agent-config.yaml",
}


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as f:
        return yaml.safe_load(f) or {}


def get_value(data: dict, path: str):
    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def normalize_release_image(image: str) -> str:
    """Digest identity is independent of the declared source or mirror hostname."""
    return image or ""


def load_env(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
            value = raw[1:-1]
        else:
            try:
                value = shlex.split(raw, posix=True)[0] if raw else ""
            except ValueError:
                value = raw.strip('"\'')
        result[key] = value
    return result


def release_images_from_env(env: dict[str, str]) -> list[dict]:
    raw = env.get("RELEASE_IMAGES", "")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\])", raw)
        return json.loads(match.group(1)) if match else []


def record(rows: list[dict], check: str, expected, actual, ok: bool):
    rows.append(
        {
            "check": check,
            "expected": expected,
            "actual": actual,
            "result": "PASS" if ok else "FAIL",
        }
    )


def write_report(rows: list[dict], output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ABI Embedded Manifest Validation",
        "",
        "| Check | Expected | Actual | Result |",
        "|-------|----------|--------|--------|",
    ]
    for row in rows:
        expected = str(row["expected"]).replace("|", "\\|").replace("\n", "<br>")
        actual = str(row["actual"]).replace("|", "\\|").replace("\n", "<br>")
        icon = "✅" if row["result"] == "PASS" else "❌"
        lines.append(f"| {row['check']} | {expected} | {actual} | {icon} {row['result']} |")
    failures = sum(1 for row in rows if row["result"] != "PASS")
    lines.extend(["", f"**Summary:** {len(rows) - failures}/{len(rows)} checks passed", ""])
    output.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--embedded-dir", required=True, type=Path)
    parser.add_argument("--release-selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rows = []
    metadata = load_yaml(args.data_dir / "metadata.yaml")
    install_config = load_yaml(args.data_dir / "install-config.yaml")
    agent_config = load_yaml(args.data_dir / "agent-config.yaml")
    release_selection = json.loads(args.release_selection.read_text())

    embedded = {}
    for key, filename in MANIFESTS.items():
        path = args.embedded_dir / filename
        record(rows, f"{filename} collected", "present", "present" if path.exists() else "missing", path.exists())
        if path.exists():
            embedded[key] = load_yaml(path)

    env_path = args.embedded_dir / "assisted-service.env"
    record(rows, "assisted-service.env collected", "present", "present" if env_path.exists() else "missing", env_path.exists())
    assisted_env = load_env(env_path) if env_path.exists() else {}

    expected_version = metadata.get("ocpVersion")
    cis = embedded.get("cluster-image-set", {})
    cis_name = get_value(cis, "metadata.name")
    cis_release = get_value(cis, "spec.releaseImage") or get_value(cis, "spec.releaseimage") or ""
    record(rows, "ClusterImageSet name includes version", expected_version, cis_name, bool(expected_version and cis_name and expected_version in cis_name))
    record(rows, "ClusterImageSet releaseImage digest", release_selection.get("releaseDigest"), cis_release, normalize_release_image(cis_release).endswith(f"@{release_selection.get('releaseDigest')}") or cis_release.endswith(f"@{release_selection.get('releaseDigest')}"))

    releases = release_images_from_env(assisted_env)
    release_versions = {str(item.get("openshift_version") or item.get("version") or "") for item in releases}
    release_urls = [str(item.get("url") or item.get("release_image") or "") for item in releases]
    record(rows, "RELEASE_IMAGES version", expected_version, sorted(release_versions), expected_version in release_versions)
    record(rows, "RELEASE_IMAGES release digest", release_selection.get("releaseDigest"), release_urls, any(url.endswith(f"@{release_selection.get('releaseDigest')}") for url in release_urls))

    infraenv = embedded.get("infraenv", {})
    record(rows, "InfraEnv cpuArchitecture", "x86_64", get_value(infraenv, "spec.cpuArchitecture"), get_value(infraenv, "spec.cpuArchitecture") == "x86_64")
    expected_ntp = metadata.get("ntpServers", [])
    infra_ntp = get_value(infraenv, "spec.additionalNTPSources") or []
    embedded_agent_ntp = get_value(embedded.get("agent-config", {}), "additionalNTPSources") or []
    source_agent_ntp = agent_config.get("additionalNTPSources", [])
    record(rows, "InfraEnv additionalNTPSources", expected_ntp, infra_ntp, all(source in infra_ntp for source in expected_ntp))
    record(rows, "AgentConfig additionalNTPSources", source_agent_ntp, embedded_agent_ntp, embedded_agent_ntp == source_agent_ntp)

    aci = embedded.get("agent-cluster-install", {})
    node_count = len(metadata.get("nodes", []))
    control_replicas = get_value(install_config, "controlPlane.replicas")
    worker_replicas = (get_value(install_config, "compute") or [{}])[0].get("replicas", 0)
    expected_masters = control_replicas if control_replicas is not None else node_count
    actual_masters = (
        get_value(aci, "spec.provisionRequirements.controlPlaneAgents")
        or get_value(aci, "spec.provisionRequirements.controlPlaneAgentsBareMetal")
        or get_value(aci, "spec.controlPlaneAgents")
    )
    actual_workers = (
        get_value(aci, "spec.provisionRequirements.workerAgents")
        or get_value(aci, "spec.provisionRequirements.workerAgentsBareMetal")
        or get_value(aci, "spec.workerAgents")
        or 0
    )
    record(rows, "AgentClusterInstall control plane agents", expected_masters, actual_masters, int(actual_masters or -1) == int(expected_masters))
    record(rows, "AgentClusterInstall worker agents", worker_replicas, actual_workers, int(actual_workers or 0) == int(worker_replicas or 0))

    expected_network_type = metadata.get("networkType")
    install_network_type = get_value(install_config, "networking.networkType")
    actual_network_type = get_value(aci, "spec.networking.networkType") or get_value(aci, "spec.networkType") or install_network_type
    record(rows, "networkType", expected_network_type, actual_network_type, actual_network_type == expected_network_type == install_network_type)

    api_vips = get_value(install_config, "platform.baremetal.apiVIPs") or []
    ingress_vips = get_value(install_config, "platform.baremetal.ingressVIPs") or []
    aci_api_vips = get_value(aci, "spec.apiVIPs") or get_value(aci, "spec.apiVIP") or []
    aci_ingress_vips = get_value(aci, "spec.ingressVIPs") or get_value(aci, "spec.ingressVIP") or []
    record(rows, "API VIPs", api_vips, aci_api_vips, set(api_vips) <= set(aci_api_vips if isinstance(aci_api_vips, list) else [aci_api_vips]))
    record(rows, "Ingress VIPs", ingress_vips, aci_ingress_vips, set(ingress_vips) <= set(aci_ingress_vips if isinstance(aci_ingress_vips, list) else [aci_ingress_vips]))

    write_report(rows, args.output)
    failures = [row for row in rows if row["result"] != "PASS"]
    if failures:
        print(f"ABI embedded manifest validation failed: {len(failures)} check(s)")
        for row in failures:
            print(f"FAIL {row['check']}: expected={row['expected']} actual={row['actual']}")
        raise SystemExit(1)
    print(f"ABI embedded manifest validation passed: {len(rows)} checks")


if __name__ == "__main__":
    main()
