"""Pytest configuration for cluster contract verification.

Loads declared intent from data/openshift/<cluster>/ and produces a markdown
report from pytest user_properties.
"""

import json
from pathlib import Path

import pytest
import yaml


def pytest_addoption(parser):
    parser.addoption("--cluster-name", required=True, help="Cluster name (e.g. example-management)")
    parser.addoption("--snapshot-file", required=True, help="Path to collected cluster state JSON")


@pytest.fixture(scope="session")
def cluster_name(request):
    return request.config.getoption("--cluster-name")


@pytest.fixture(scope="session")
def repo_root():
    return Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        pytest.fail(f"Required intent file not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def cluster_intent(repo_root, cluster_name):
    """Load current data/openshift/<cluster>/ intent contract."""
    intent_dir = repo_root / "data" / "openshift" / cluster_name
    return {
        "metadata": _load_yaml(intent_dir / "metadata.yaml"),
        "install_config": _load_yaml(intent_dir / "install-config.yaml"),
        "agent_config": _load_yaml(intent_dir / "agent-config.yaml"),
    }


@pytest.fixture(scope="session")
def metadata(cluster_intent):
    return cluster_intent["metadata"]


@pytest.fixture(scope="session")
def install_config(cluster_intent):
    return cluster_intent["install_config"]


@pytest.fixture(scope="session")
def agent_config(cluster_intent):
    return cluster_intent["agent_config"]


@pytest.fixture(scope="session")
def snapshot(request):
    """Load the collected cluster state snapshot."""
    path = Path(request.config.getoption("--snapshot-file"))
    if not path.exists():
        pytest.fail(f"Snapshot file not found: {path}")
    with path.open() as f:
        return json.load(f)


@pytest.fixture(scope="session")
def actual_nodes(snapshot):
    """Extract processed node list from snapshot."""
    items = snapshot.get("nodes", {}).get("items", [])
    result = []
    for node in items:
        labels = node.get("metadata", {}).get("labels", {})
        roles = sorted(
            key.removeprefix("node-role.kubernetes.io/")
            for key, value in labels.items()
            if key.startswith("node-role.kubernetes.io/") and value in ("", "true")
        )
        hostname = node["metadata"]["name"]
        ips = [
            a["address"]
            for a in node.get("status", {}).get("addresses", [])
            if a["type"] == "InternalIP"
        ]
        conditions = {
            c["type"]: c["status"]
            for c in node.get("status", {}).get("conditions", [])
        }
        result.append(
            {
                "hostname": hostname,
                "short_name": hostname.split(".")[0],
                "ip": ips[0] if ips else None,
                "roles": roles,
                "conditions": conditions,
                "unschedulable": node.get("spec", {}).get("unschedulable", False),
            }
        )
    return result


def _node_intents(metadata: dict, agent_config: dict) -> list[dict]:
    metadata_nodes = {node["name"]: node for node in metadata.get("nodes", [])}
    intents = []
    for host in agent_config.get("hosts", []):
        hostname = host["hostname"]
        short_name = hostname.split(".")[0]
        addresses = [address["ip"] for interface in host["networkConfig"]["interfaces"]
                     for address in interface.get("ipv4", {}).get("address", [])]
        declared = metadata_nodes.get(short_name, {}).get("ip")
        if declared:
            assert declared in addresses, f"{hostname}: metadata IP is absent from AgentConfig"
            ip = declared
        else:
            defaults = {route["next-hop-interface"] for route in host["networkConfig"].get("routes", {}).get("config", [])
                        if route.get("destination") == "0.0.0.0/0"}
            management = [address["ip"] for interface in host["networkConfig"]["interfaces"]
                          if interface["name"] in defaults
                          for address in interface.get("ipv4", {}).get("address", [])]
            assert len(management) == 1, f"{hostname}: cannot identify a unique declared default-route address"
            ip = management[0]
        intents.append(
            {
                "hostname": hostname,
                "short_name": short_name,
                "role": host["role"],
                "ip": ip,
                "metadata": metadata_nodes.get(short_name, {}),
            }
        )
    return intents


@pytest.fixture(scope="session")
def node_intents(metadata, agent_config):
    return _node_intents(metadata, agent_config)


def pytest_generate_tests(metafunc):
    if "node_intent" in metafunc.fixturenames:
        cluster_name = metafunc.config.getoption("--cluster-name")
        repo_root = Path(__file__).resolve().parent.parent
        intent_dir = repo_root / "data" / "openshift" / cluster_name
        metadata_path = intent_dir / "metadata.yaml"
        agent_path = intent_dir / "agent-config.yaml"
        if metadata_path.exists() and agent_path.exists():
            metadata = _load_yaml(metadata_path)
            agent_config = _load_yaml(agent_path)
            nodes = _node_intents(metadata, agent_config)
            metafunc.parametrize("node_intent", nodes, ids=[n["hostname"] for n in nodes])
        else:
            metafunc.parametrize("node_intent", [])


_report_rows = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        props = dict(item.user_properties)
        if report.passed:
            result = "PASS"
        elif report.skipped:
            result = "SKIP"
        else:
            result = "FAIL"
        _report_rows.append(
            {
                "test": item.nodeid.split("::")[-1],
                "expected": props.get("expected", "—"),
                "actual": props.get("actual", "—"),
                "result": result,
            }
        )


def pytest_sessionfinish(session, exitstatus):
    cluster_name = session.config.getoption("--cluster-name", default=None)
    if not cluster_name or not _report_rows:
        return

    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"contract-report-{cluster_name}.md"

    lines = [
        f"# Contract Verification Report: {cluster_name}\n",
        "",
        "| Check | Expected | Actual | Result |",
        "|-------|----------|--------|--------|",
    ]
    for row in _report_rows:
        exp = str(row["expected"]).replace("|", "\\|").replace("\n", "<br>")
        act = str(row["actual"]).replace("|", "\\|").replace("\n", "<br>")
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️"}.get(row["result"], "?")
        lines.append(f"| {row['test']} | {exp} | {act} | {icon} {row['result']} |")

    passed = sum(1 for r in _report_rows if r["result"] == "PASS")
    skipped = sum(1 for r in _report_rows if r["result"] == "SKIP")
    total = len(_report_rows)
    lines.extend(
        [
            "",
            f"**Summary:** {passed}/{total} checks passed, {skipped} skipped",
            "",
            "## Raw Evidence",
            "",
            f"- Cluster snapshot: `cluster-state-{cluster_name}.json`",
            f"- JUnit: `junit-{cluster_name}.xml`",
            "",
        ]
    )

    report_path.write_text("\n".join(lines))
