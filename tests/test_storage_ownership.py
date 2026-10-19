from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_pod_has_no_active_storage_ownership() -> None:
    active_paths = [
        ROOT / "openshift" / "modes",
        ROOT / "scripts",
    ]
    offenders = []
    for base in active_paths:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".j2", ".yaml", ".yml"}:
                continue
            text = path.read_text(errors="ignore").lower()
            if "mdadm --create" in text or "kind: lvmcluster" in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_legacy_generated_mdadm_manifests_are_retired() -> None:
    assert list((ROOT / "openshift" / "data").glob("*/manifests/99-mdadm-nvme-raid10.yaml")) == []


def test_renderer_still_contains_gitops_bootstrap_path() -> None:
    text = (ROOT / "scripts" / "render-cluster-config.py").read_text()
    assert "gitops" in text.lower()
    assert "install-config.yaml.j2" in text
    assert "agent-config.yaml.j2" in text
