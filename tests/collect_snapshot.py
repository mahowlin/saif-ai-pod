#!/usr/bin/env python3
"""Collect cluster state snapshot for contract verification.

Usage:
    python tests/collect_snapshot.py <cluster-name> [--kubeconfig PATH] [--output PATH]

Runs oc commands against a live cluster and writes verifiable state into one
JSON file. Pytest then compares the snapshot to data/openshift/<cluster>/.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def oc_json(*args: str) -> dict:
    """Run oc get <args> -o json, return parsed dict."""
    cmd = ["oc", *args, "-o", "json"]
    result = run(cmd)
    if result.returncode != 0:
        print(f"WARNING: {' '.join(cmd)} failed: {result.stderr.strip()}", file=sys.stderr)
        return {"_error": result.stderr.strip()}
    return json.loads(result.stdout)


def oc_text(*args: str, timeout: int = 60) -> str:
    """Run oc command, return stdout as text."""
    cmd = ["oc", *args]
    result = run(cmd, timeout=timeout)
    if result.returncode != 0:
        return f"_error: {result.stderr.strip()}"
    return result.stdout.strip()


def find_cilium_namespace() -> str | None:
    """Find which namespace Cilium lives in."""
    for ns in ("cilium", "openshift-cilium"):
        result = run(
            [
                "oc",
                "get",
                "pods",
                "-n",
                ns,
                "-l",
                "k8s-app=cilium",
                "--no-headers",
                "--ignore-not-found",
            ],
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return ns
    return None


def collect_cilium(cilium_ns: str | None) -> dict:
    """Collect Cilium-specific state."""
    if not cilium_ns:
        return {"namespace": None, "found": False}

    pods = oc_json("get", "pods", "-n", cilium_ns)
    agent_pod = oc_text(
        "get",
        "pods",
        "-n",
        cilium_ns,
        "-l",
        "k8s-app=cilium",
        "-o",
        "name",
        "--no-headers",
    )
    agent_name = agent_pod.strip().split("\n")[0] if agent_pod and not agent_pod.startswith("_error") else None

    dbg_brief = None
    dbg_full = None
    if agent_name:
        dbg_brief = oc_text("exec", "-n", cilium_ns, agent_name, "--", "cilium-dbg", "status", "--brief")
        dbg_full = oc_text("exec", "-n", cilium_ns, agent_name, "--", "cilium-dbg", "status")

    return {
        "namespace": cilium_ns,
        "found": True,
        "pods": pods,
        "agent_pod": agent_name,
        "dbg_status_brief": dbg_brief,
        "dbg_status_full": dbg_full,
    }


def debug_node(hostname: str, *command: str, timeout: int = 120) -> str:
    """Run command on a node through oc debug node/<name>."""
    return oc_text("debug", f"node/{hostname}", "--quiet", "--", "chroot", "/host", *command, timeout=timeout)


def collect_ntp(nodes: dict) -> dict:
    """Collect chrony/NTP state per node through oc debug."""
    results = {}
    for node in nodes.get("items", []):
        hostname = node.get("metadata", {}).get("name", "")
        if not hostname:
            continue
        results[hostname] = {
            "chronyc_tracking": debug_node(hostname, "chronyc", "tracking"),
            "chronyc_sources": debug_node(hostname, "chronyc", "sources", "-n"),
            "timedatectl": debug_node(hostname, "timedatectl", "show", "-p", "NTPSynchronized", "--value"),
        }
    return results


def collect(cluster_name: str) -> dict:
    """Collect all verifiable cluster state into a dict."""
    print(f"Collecting state for cluster '{cluster_name}'...")

    cilium_ns = find_cilium_namespace()
    nodes = oc_json("get", "nodes")

    snapshot = {
        "cluster_name": cluster_name,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "nodes": nodes,
        "infrastructure": oc_json("get", "infrastructure", "cluster"),
        "clusterversion": oc_json("get", "clusterversion", "version"),
        "clusteroperators": oc_json("get", "clusteroperators"),
        "network_operator": oc_json("get", "network.operator", "cluster"),
        "network_config": oc_json("get", "network.config", "cluster"),
        "kube_proxy_pods": oc_json("get", "pods", "-n", "openshift-kube-proxy"),
        "idms": oc_json("get", "imagedigestmirrorset"),
        "itms": oc_json("get", "imagetagmirrorset"),
        "cilium": collect_cilium(cilium_ns),
        "ntp": collect_ntp(nodes),
    }

    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cluster_name", help="Cluster name (e.g. example-management)")
    parser.add_argument("--kubeconfig", help="Path to kubeconfig file")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    if args.kubeconfig:
        os.environ["KUBECONFIG"] = args.kubeconfig

    snapshot = collect(args.cluster_name)

    output_path = args.output
    if not output_path:
        reports_dir = Path(__file__).parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        output_path = str(reports_dir / f"cluster-state-{args.cluster_name}.json")

    with open(output_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Snapshot written to {output_path}")


if __name__ == "__main__":
    main()
