from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IsovalentPrerequisiteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_module(
            "validate_selected_cluster_contract", SCRIPTS / "validate-selected-cluster-contract.py"
        )
        cls.enricher = load_module("enrich_cilium_day1_manifests", SCRIPTS / "enrich-cilium-day1-manifests.py")
        cls.cluster_contract = load_module("test_cluster_contract", REPO_ROOT / "tests" / "test_cluster_contract.py")

    def test_compact_day1_cilium_contract_is_two_sided(self) -> None:
        with tempfile.TemporaryDirectory(prefix="compact-kpr-") as tmp:
            cluster_dir = Path(tmp) / "example-management"
            shutil.copytree(REPO_ROOT / "data" / "openshift" / "example-management", cluster_dir)
            self.enricher.render_manifests(REPO_ROOT, cluster_dir)

            errors: list[str] = []
            metadata = self.validator.load_yaml(cluster_dir / "metadata.yaml")
            self.validator.validate_cilium(cluster_dir, metadata, errors)
            self.assertEqual(errors, [])

            network_path = cluster_dir / "manifests" / "cluster-network-02-config-local.yml"
            network = yaml.safe_load(network_path.read_text())
            network["spec"]["deployKubeProxy"] = True
            network_path.write_text(yaml.safe_dump(network, sort_keys=False))
            errors = []
            self.validator.validate_cilium(cluster_dir, metadata, errors)
            self.assertTrue(any("deployKubeProxy must be false" in error for error in errors))

    def test_sno_day2_migration_contract_is_two_sided(self) -> None:
        migration = REPO_ROOT / "openshift" / "data" / "example-node-1" / "cilium-migration"
        network = yaml.safe_load((migration / "network-config.yaml").read_text())
        cilium = yaml.safe_load((migration / "ciliumconfig.yaml").read_text())

        self.assertIs(network["spec"]["deployKubeProxy"], False)
        self.assertEqual(network["spec"]["networkType"], "Cilium")
        self.assertIs(cilium["spec"]["kubeProxyReplacement"], True)
        self.assertIs(cilium["spec"]["socketLB"]["hostNamespaceOnly"], True)

    def test_kube_proxy_snapshot_evidence_semantics(self) -> None:
        collect = self.cluster_contract._collected_kube_proxy_pods
        self.assertIsNone(collect({}))
        self.assertEqual(collect({"kube_proxy_pods": {"items": []}}), [])
        with self.assertRaisesRegex(ValueError, "collection failed"):
            collect({"kube_proxy_pods": {"_error": "API timeout"}})
        with self.assertRaisesRegex(ValueError, "no items list"):
            collect({"kube_proxy_pods": {}})

    def test_historical_sno_snapshot_proves_kpr_but_not_pod_absence(self) -> None:
        snapshot = json.loads((REPO_ROOT / "tests" / "fixtures" / "cluster-state-example-node-1.json").read_text())
        self.assertIs(snapshot["network_operator"]["spec"]["deployKubeProxy"], False)
        self.assertRegex(snapshot["cilium"]["dbg_status_full"], r"KubeProxyReplacement:\s+True")
        self.assertIsNone(self.cluster_contract._collected_kube_proxy_pods(snapshot))


if __name__ == "__main__":
    unittest.main()
