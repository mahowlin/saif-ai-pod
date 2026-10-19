"""Cluster input-output contract verification tests.

Each test compares declared intent in data/openshift/<cluster>/ against actual
OpenShift cluster state from tests/collect_snapshot.py. Tests store
expected/actual values as user_properties for the markdown report.
"""

import ipaddress
import re

import pytest


def _conditions(resource: dict) -> dict[str, str]:
    return {
        condition.get("type"): condition.get("status")
        for condition in resource.get("status", {}).get("conditions", [])
    }


def _idms_sources(items: list[dict]) -> list[str]:
    sources = []
    for item in items:
        for mirror in item.get("spec", {}).get("imageDigestMirrors", []):
            sources.append(mirror.get("source", ""))
    return sorted(source for source in sources if source)


def _idms_mirrors(items: list[dict]) -> list[str]:
    mirrors = []
    for item in items:
        for mirror in item.get("spec", {}).get("imageDigestMirrors", []):
            mirrors.extend(mirror.get("mirrors", []))
    return sorted(mirror for mirror in mirrors if mirror)


def _itms_mirrors(items: list[dict]) -> list[str]:
    mirrors = []
    for item in items:
        for mirror in item.get("spec", {}).get("imageTagMirrors", []):
            mirrors.extend(mirror.get("mirrors", []))
    return sorted(mirror for mirror in mirrors if mirror)


def _chrony_reference_ids(tracking: str) -> set[str]:
    match = re.search(r"Reference ID\s*:\s*([0-9A-Fa-f:.]+)", tracking)
    if not match:
        return set()
    ref = match.group(1)
    refs = {ref}
    try:
        refs.add(str(ipaddress.ip_address(int(ref, 16))))
    except ValueError:
        pass
    return refs


def _chrony_has_source(state: dict, source: str) -> bool:
    sources_output = state.get("chronyc_sources", "") or ""
    tracking = state.get("chronyc_tracking", "") or ""
    return source in sources_output or source in _chrony_reference_ids(tracking)


def _collected_kube_proxy_pods(snapshot: dict) -> list[dict] | None:
    """Return collected kube-proxy pods, or None for a legacy snapshot."""
    if "kube_proxy_pods" not in snapshot:
        return None
    collection = snapshot["kube_proxy_pods"]
    if not isinstance(collection, dict):
        raise ValueError("kube-proxy pod collection is not an object")
    if collection.get("_error"):
        raise ValueError(f"kube-proxy pod collection failed: {collection['_error']}")
    items = collection.get("items")
    if not isinstance(items, list):
        raise ValueError("kube-proxy pod collection has no items list")
    return items


class TestDeclaredIntentFiles:
    def test_cluster_name_matches_metadata(self, cluster_name, metadata, install_config, agent_config, request):
        names = {
            "input": cluster_name,
            "metadata": metadata.get("clusterName"),
            "install": install_config.get("metadata", {}).get("name"),
            "agent": agent_config.get("metadata", {}).get("name"),
        }
        request.node.user_properties.append(("expected", cluster_name))
        request.node.user_properties.append(("actual", names))
        assert all(value == cluster_name for value in names.values())

    def test_network_type_matches_install_config(self, metadata, install_config, request):
        expected = metadata["networkType"]
        actual = install_config.get("networking", {}).get("networkType")
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_ntp_sources_match_metadata(self, metadata, agent_config, request):
        expected = metadata.get("ntpServers", [])
        actual = agent_config.get("additionalNTPSources", [])
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected


class TestNodes:
    def test_node_present(self, node_intent, actual_nodes, request):
        expected = node_intent["hostname"]
        actual_hostnames = {node["hostname"] for node in actual_nodes}
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", expected if expected in actual_hostnames else "NOT FOUND"))
        assert expected in actual_hostnames

    def test_node_ip(self, node_intent, actual_nodes, request):
        expected = node_intent["ip"]
        actual = next((node for node in actual_nodes if node["hostname"] == node_intent["hostname"]), None)
        actual_ip = actual["ip"] if actual else "NODE NOT FOUND"
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual_ip))
        assert actual is not None
        assert actual_ip == expected

    def test_node_role(self, node_intent, actual_nodes, request):
        expected = "master" if node_intent["role"] == "master" else node_intent["role"]
        actual = next((node for node in actual_nodes if node["hostname"] == node_intent["hostname"]), None)
        roles = actual["roles"] if actual else []
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", roles))
        assert actual is not None
        assert expected in roles

    def test_node_ready(self, node_intent, actual_nodes, request):
        actual = next((node for node in actual_nodes if node["hostname"] == node_intent["hostname"]), None)
        ready = actual["conditions"].get("Ready", "Unknown") if actual else "NODE NOT FOUND"
        request.node.user_properties.append(("expected", "True"))
        request.node.user_properties.append(("actual", ready))
        assert ready == "True"

    def test_node_not_network_unavailable(self, node_intent, actual_nodes, request):
        actual = next((node for node in actual_nodes if node["hostname"] == node_intent["hostname"]), None)
        value = actual["conditions"].get("NetworkUnavailable", "False") if actual else "NODE NOT FOUND"
        request.node.user_properties.append(("expected", "False"))
        request.node.user_properties.append(("actual", value))
        assert value == "False"

    def test_node_no_pressure(self, node_intent, actual_nodes, request):
        actual = next((node for node in actual_nodes if node["hostname"] == node_intent["hostname"]), None)
        pressures = {}
        if actual:
            for pressure in ("MemoryPressure", "DiskPressure", "PIDPressure"):
                pressures[pressure] = actual["conditions"].get(pressure, "Unknown")
        failing = {key: value for key, value in pressures.items() if value == "True"}
        request.node.user_properties.append(("expected", "No pressure conditions"))
        request.node.user_properties.append(("actual", failing if failing else "None"))
        assert not failing


class TestCluster:
    def test_node_count(self, node_intents, actual_nodes, request):
        expected = len(node_intents)
        actual = len(actual_nodes)
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_api_endpoint(self, install_config, snapshot, request):
        expected = f"api.{install_config['metadata']['name']}.{install_config['baseDomain']}"
        api_url = snapshot.get("infrastructure", {}).get("status", {}).get("apiServerURL", "")
        actual = api_url.replace("https://", "").split(":")[0]
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_openshift_version(self, metadata, snapshot, request):
        expected = metadata["ocpVersion"]
        actual = snapshot.get("clusterversion", {}).get("status", {}).get("desired", {}).get("version", "")
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_clusterversion_available(self, snapshot, request):
        available = _conditions(snapshot.get("clusterversion", {})).get("Available", "Unknown")
        request.node.user_properties.append(("expected", "True"))
        request.node.user_properties.append(("actual", available))
        assert available == "True"

    def test_clusterversion_not_degraded(self, snapshot, request):
        degraded = _conditions(snapshot.get("clusterversion", {})).get("Degraded", "Unknown")
        request.node.user_properties.append(("expected", "not True"))
        request.node.user_properties.append(("actual", degraded))
        assert degraded == "False"

    def test_clusteroperators_available(self, metadata, snapshot, request):
        operators = snapshot.get("clusteroperators", {}).get("items", [])
        assert isinstance(operators, list) and operators, "required operator observation is empty or failed"
        disconnected = "disconnectedCatalogs" in metadata.get("capabilities", [])
        allowed_degraded = {"insights"} if disconnected else set()
        unhealthy = []
        documented = []
        for operator in operators:
            name = operator.get("metadata", {}).get("name", "unknown")
            conditions = _conditions(operator)
            healthy = (
                conditions.get("Available") == "True"
                and conditions.get("Progressing") == "False"
                and conditions.get("Degraded") == "False"
            )
            documented_exception = name in allowed_degraded and conditions.get("Available") == "True"
            if not healthy and documented_exception:
                documented.append(name)
            elif not healthy:
                unhealthy.append(name)
        request.node.user_properties.append(("expected", "all healthy; insights may degrade in disconnected mode"))
        request.node.user_properties.append(("actual", {"unhealthy": unhealthy, "documented": documented}))
        assert not unhealthy


class TestNetworking:
    def test_cni_type(self, metadata, snapshot, request):
        expected = metadata["networkType"]
        actual = snapshot.get("network_operator", {}).get("spec", {}).get("defaultNetwork", {}).get("type", "")
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_cluster_network_cidr(self, install_config, snapshot, request):
        expected = install_config["networking"]["clusterNetwork"][0]["cidr"]
        networks = snapshot.get("network_config", {}).get("spec", {}).get("clusterNetwork", [])
        actual = networks[0].get("cidr") if networks else ""
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_cluster_network_host_prefix(self, install_config, snapshot, request):
        expected = install_config["networking"]["clusterNetwork"][0]["hostPrefix"]
        networks = snapshot.get("network_config", {}).get("spec", {}).get("clusterNetwork", [])
        actual = networks[0].get("hostPrefix") if networks else None
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_service_network(self, install_config, snapshot, request):
        expected = install_config["networking"]["serviceNetwork"]
        actual = snapshot.get("network_config", {}).get("spec", {}).get("serviceNetwork", [])
        request.node.user_properties.append(("expected", expected))
        request.node.user_properties.append(("actual", actual))
        assert actual == expected

    def test_node_ips_within_machine_network(self, install_config, actual_nodes, request):
        import ipaddress

        cidrs = [network["cidr"] for network in install_config["networking"].get("machineNetwork", [])]
        networks = [ipaddress.ip_network(cidr) for cidr in cidrs]
        outside = {
            node["hostname"]: node["ip"]
            for node in actual_nodes
            if not any(ipaddress.ip_address(node["ip"]) in network for network in networks)
        }
        request.node.user_properties.append(("expected", cidrs))
        request.node.user_properties.append(("actual", outside if outside else "all node IPs within machineNetwork"))
        assert not outside


class TestDisconnectedImagePolicy:
    def test_idms_present_when_required(self, metadata, snapshot, request):
        required = "disconnectedCatalogs" in metadata.get("capabilities", [])
        items = snapshot.get("idms", {}).get("items", [])
        request.node.user_properties.append(("expected", ">= 1 IDMS" if required else "optional"))
        request.node.user_properties.append(("actual", f"{len(items)} IDMS"))
        if required:
            assert len(items) >= 1

    def test_idms_mirrors_use_local_registry(self, metadata, snapshot, request):
        if "disconnectedCatalogs" not in metadata.get("capabilities", []):
            pytest.skip("Disconnected catalogs not required by metadata")
        mirrors = _idms_mirrors(snapshot.get("idms", {}).get("items", []))
        registry = metadata.get("imageDelivery", {}).get("registry")
        assert registry, "metadata.imageDelivery.registry is required"
        non_local = [mirror for mirror in mirrors if not mirror.startswith(registry.rstrip("/") + "/")]
        request.node.user_properties.append(("expected", f"all IDMS mirrors under {registry}"))
        request.node.user_properties.append(("actual", non_local if non_local else f"{len(mirrors)} local mirrors"))
        assert mirrors
        assert not non_local

    def test_release_idms_sources_present(self, install_config, snapshot, request):
        expected_sources = sorted(source["source"] for source in install_config.get("imageDigestSources", []))
        actual_sources = _idms_sources(snapshot.get("idms", {}).get("items", []))
        missing = [source for source in expected_sources if source not in actual_sources]
        request.node.user_properties.append(("expected", expected_sources))
        request.node.user_properties.append(("actual", actual_sources))
        assert not missing

    def test_itms_mirrors_use_local_registry_when_present(self, metadata, snapshot, request):
        mirrors = _itms_mirrors(snapshot.get("itms", {}).get("items", []))
        registry = metadata.get("imageDelivery", {}).get("registry")
        assert registry, "metadata.imageDelivery.registry is required"
        non_local = [mirror for mirror in mirrors if not mirror.startswith(registry.rstrip("/") + "/")]
        request.node.user_properties.append(("expected", f"all ITMS mirrors under {registry} if present"))
        request.node.user_properties.append(("actual", non_local if non_local else f"{len(mirrors)} local mirrors"))
        assert not non_local


class TestChrony:
    def test_ntp_sources_present(self, metadata, snapshot, request):
        expected_sources = metadata.get("ntpServers", [])
        ntp = snapshot.get("ntp", {})
        nodes = snapshot.get("nodes", {}).get("items", [])
        expected_nodes = {node["metadata"]["name"] for node in nodes}
        assert expected_nodes and isinstance(ntp, dict) and set(ntp) >= expected_nodes, "missing NTP observation for a node"
        missing_by_node = {}
        for hostname, state in ntp.items():
            missing = [source for source in expected_sources if not _chrony_has_source(state, source)]
            if missing:
                missing_by_node[hostname] = missing
        request.node.user_properties.append(("expected", expected_sources))
        request.node.user_properties.append(("actual", missing_by_node if missing_by_node else "present on all nodes"))
        assert not missing_by_node

    def test_ntp_synchronized(self, snapshot, request):
        ntp = snapshot.get("ntp", {})
        nodes = snapshot.get("nodes", {}).get("items", [])
        expected_nodes = {node["metadata"]["name"] for node in nodes}
        assert expected_nodes and isinstance(ntp, dict) and set(ntp) >= expected_nodes, "missing NTP observation for a node"
        unsynced = {}
        for hostname, state in ntp.items():
            timedatectl = (state.get("timedatectl") or "").strip()
            tracking = state.get("chronyc_tracking", "") or ""
            synchronized = timedatectl == "yes" or re.search(r"Leap status\s*:\s*Normal", tracking) is not None
            if not synchronized:
                unsynced[hostname] = {
                    "timedatectl": timedatectl,
                    "tracking": tracking.splitlines()[:4],
                }
        request.node.user_properties.append(("expected", "NTP synchronized on all nodes"))
        request.node.user_properties.append(("actual", unsynced if unsynced else "all synchronized"))
        assert not unsynced


class TestCilium:
    def test_kube_proxy_replacement_enabled(self, metadata, snapshot, request):
        if metadata.get("networkType") != "Cilium":
            pytest.skip("Cilium not expected by metadata")
        deploy_kube_proxy = snapshot.get("network_operator", {}).get("spec", {}).get("deployKubeProxy")
        status = snapshot.get("cilium", {}).get("dbg_status_full", "") or ""
        actual = {
            "deployKubeProxy": deploy_kube_proxy,
            "kubeProxyReplacement": "True" if re.search(r"KubeProxyReplacement:\s+True", status) else "not True",
        }
        request.node.user_properties.append(("expected", "deployKubeProxy=false, KubeProxyReplacement=True"))
        request.node.user_properties.append(("actual", actual))
        assert deploy_kube_proxy is False
        assert actual["kubeProxyReplacement"] == "True"

    def test_openshift_kube_proxy_pods_absent(self, metadata, snapshot, request):
        if metadata.get("networkType") != "Cilium":
            pytest.skip("Cilium not expected by metadata")
        try:
            kube_proxy_pods = _collected_kube_proxy_pods(snapshot)
        except ValueError as exc:
            pytest.fail(str(exc))
        if kube_proxy_pods is None:
            request.node.user_properties.append(("expected", "zero openshift-kube-proxy pods"))
            request.node.user_properties.append(("actual", "NOT COLLECTED"))
            pytest.skip("NOT COLLECTED in this historical snapshot")
        request.node.user_properties.append(("expected", "zero openshift-kube-proxy pods"))
        request.node.user_properties.append(("actual", len(kube_proxy_pods)))
        assert not kube_proxy_pods

    def test_cilium_pods_running_when_expected(self, metadata, snapshot, request):
        expected_cilium = metadata.get("networkType") == "Cilium"
        cilium = snapshot.get("cilium", {})
        pods = cilium.get("pods", {}).get("items", [])
        total = len(pods)
        running = sum(1 for pod in pods if pod.get("status", {}).get("phase") == "Running")
        request.node.user_properties.append(("expected", "Cilium pods running" if expected_cilium else "not required"))
        request.node.user_properties.append(("actual", f"{running}/{total} Running"))
        if expected_cilium:
            assert total > 0
            assert running == total

    def test_cilium_status_ok_when_expected(self, metadata, snapshot, request):
        if metadata.get("networkType") != "Cilium":
            pytest.skip("Cilium not expected by metadata")
        brief = snapshot.get("cilium", {}).get("dbg_status_brief", "")
        request.node.user_properties.append(("expected", "OK"))
        request.node.user_properties.append(("actual", brief))
        assert brief == "OK"
