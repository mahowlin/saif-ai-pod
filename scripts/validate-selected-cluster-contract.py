#!/usr/bin/env python3
"""Validate the selected SAIF OpenShift cluster folder contract."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import subprocess
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

import yaml


REQUIRED_SOURCES = {
    "ocp-install-core": ["quay.io/openshift-release-dev/ocp-release"],
    "cilium-day1": ["quay.io/isovalent"],
    "gitops-bootstrap": [
        "registry.redhat.io/openshift4",
        "registry.redhat.io/openshift-gitops-1",
        "registry.redhat.io/rhel9",
    ],
}


BUNDLE_KEYS = {
    "ocp-install-core": "ocpInstallCore",
    "cilium-day1": "ciliumDay1",
    "gitops-bootstrap": "gitopsBootstrap",
}


def load_yaml(path: Path) -> dict:
    try:
        with path.open() as stream:
            data = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML document in {path}")
    return data


def load_yaml_documents(path: Path) -> list[dict]:
    try:
        with path.open() as stream:
            return [doc for doc in yaml.safe_load_all(stream) if isinstance(doc, dict)]
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc


def source_matches(source: str, required: str) -> bool:
    return source == required or source.startswith(f"{required}/") or source.startswith(f"{required}:") or source.startswith(f"{required}@")


def collect_bundle_sources(bundle_root: Path) -> set[str]:
    sources: set[str] = set()
    for path in sorted((bundle_root / "manifests").glob("*.yaml")):
        for doc in load_yaml_documents(path):
            kind = doc.get("kind")
            if kind == "ImageDigestMirrorSet":
                entries = doc.get("spec", {}).get("imageDigestMirrors", []) or []
            elif kind == "ImageTagMirrorSet":
                entries = doc.get("spec", {}).get("imageTagMirrors", []) or []
            else:
                entries = []
            for entry in entries:
                source = entry.get("source")
                if source:
                    sources.add(source)
    return sources


def bundle_root(data_dir: Path, scope: str) -> Path | None:
    key = BUNDLE_KEYS[scope]
    metadata = load_yaml(data_dir / "metadata.yaml")
    ref = metadata.get("imagePolicyBundles", {}).get(key)
    if not ref:
        return None
    if ref == scope:
        return data_dir / "image-policy-bundles" / scope
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = data_dir / candidate
    return candidate


def validate_bundle(data_dir: Path, scope: str, errors: list[str]) -> Path | None:
    root = bundle_root(data_dir, scope)
    if root is None:
        errors.append(f"metadata.yaml missing imagePolicyBundles.{BUNDLE_KEYS[scope]}")
        return None
    bundle_yaml = root / "bundle.yaml"
    manifests_dir = root / "manifests"
    if not bundle_yaml.exists():
        errors.append(f"missing {scope} bundle metadata: {bundle_yaml}")
        return root
    if not manifests_dir.is_dir() or not any(manifests_dir.glob("*.yaml")):
        errors.append(f"missing {scope} bundle manifests under {manifests_dir}")
        return root

    bundle = load_yaml(bundle_yaml)
    meta = bundle.get("metadata", {})
    spec = bundle.get("spec", {})
    if meta.get("scope") != scope or meta.get("name") != scope:
        errors.append(f"{bundle_yaml} scope/name does not match {scope}")
    missing_meta = [field for field in ("specHash", "contentHash", "version") if not meta.get(field)]
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(meta.get(key, ""))) for key in ("specHash", "contentHash")):
        errors.append(f"{bundle_yaml}: specHash/contentHash must be SHA-256 values")
    if missing_meta:
        errors.append(f"{bundle_yaml} missing metadata fields: {missing_meta}")
    missing_spec = [field for field in ("registry", "workflow", "workflowRun", "requiredSources", "manifests") if not spec.get(field)]
    if missing_spec:
        errors.append(f"{bundle_yaml} missing spec fields: {missing_spec}")

    metadata = load_yaml(data_dir / "metadata.yaml")
    expected_registry = metadata.get("imageDelivery", {}).get("registry")
    if expected_registry and spec.get("registry", "").rstrip("/") != expected_registry.rstrip("/"):
        errors.append(f"{bundle_yaml}: registry differs from selected metadata")
    required_sources = REQUIRED_SOURCES[scope]
    if scope == "cilium-day1":
        metadata = load_yaml(data_dir / "metadata.yaml")
        images = metadata.get("ciliumDay1", {}).get("images", {})
        required_sources = sorted({str(image).split("@", 1)[0].rsplit("/", 1)[0] for image in images.values() if image})
        if not required_sources:
            errors.append("selected Cilium images are required to derive mirror sources")
    declared_required = spec.get("requiredSources", []) or []
    for required in required_sources:
        if not any(source_matches(source, required) for source in declared_required):
            errors.append(f"{bundle_yaml} requiredSources does not cover {required}")

    digest = hashlib.sha256()
    for path in sorted(p for p in manifests_dir.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(manifests_dir)).encode())
        digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    if digest.hexdigest() != meta.get("contentHash"):
        errors.append(f"{bundle_yaml}: manifest contentHash mismatch")
    metadata = load_yaml(data_dir / "metadata.yaml")
    required_images = spec.get("requiredImages", [])
    if scope == "ocp-install-core":
        version = str(metadata.get("ocpVersion", ""))
        minor = ".".join(version.split(".")[:2])
        if f"platform:stable-{minor}:{version}:{version}" not in required_images:
            errors.append(f"{bundle_yaml}: receipt does not select exact OpenShift {version}")
    if scope == "cilium-day1":
        if any(image not in required_images for image in metadata.get("ciliumDay1", {}).get("images", {}).values()):
            errors.append(f"{bundle_yaml}: receipt does not select exact Cilium images")
    observed = collect_bundle_sources(root)
    for required in required_sources:
        if not any(source_matches(source, required) for source in observed):
            errors.append(f"{scope} manifests do not cover required source {required}")
    return root


def validate_common(data_dir: Path, errors: list[str]) -> tuple[dict, dict, dict]:
    required_files = ["metadata.yaml", "install-config.yaml", "agent-config.yaml"]
    for name in required_files:
        if not (data_dir / name).is_file():
            errors.append(f"missing selected cluster file {data_dir / name}")
    if errors:
        return {}, {}, {}

    metadata = load_yaml(data_dir / "metadata.yaml")
    install_config = load_yaml(data_dir / "install-config.yaml")
    agent_config = load_yaml(data_dir / "agent-config.yaml")

    cluster_name = data_dir.name
    if metadata.get("clusterName") != cluster_name:
        errors.append(f"metadata clusterName {metadata.get('clusterName')!r} does not match folder {cluster_name!r}")
    if install_config.get("metadata", {}).get("name") != cluster_name:
        errors.append("install-config metadata.name does not match selected cluster folder")
    if agent_config.get("metadata", {}).get("name") != cluster_name:
        errors.append("agent-config metadata.name does not match selected cluster folder")

    if not metadata.get("releaseRef"):
        errors.append("metadata.yaml missing releaseRef")
    if not metadata.get("ocpVersion"):
        errors.append("metadata.yaml missing ocpVersion")
    if not metadata.get("networkType"):
        errors.append("metadata.yaml missing networkType")
    if metadata.get("gitopsBootstrapPath") != f"clusters/{cluster_name}":
        errors.append("metadata gitopsBootstrapPath must point to selected cluster path")

    rendered_network_type = install_config.get("networking", {}).get("networkType")
    if rendered_network_type != metadata.get("networkType"):
        errors.append("install-config networkType does not match metadata networkType")

    expected_nodes = len(metadata.get("nodes", []) or [])
    actual_hosts = len(agent_config.get("hosts", []) or [])
    if expected_nodes != actual_hosts:
        errors.append(f"metadata nodes ({expected_nodes}) != agent-config hosts ({actual_hosts})")
    if not agent_config.get("additionalNTPSources"):
        errors.append("agent-config additionalNTPSources is required")

    return metadata, install_config, agent_config


def validate_cilium(data_dir: Path, metadata: dict, errors: list[str]) -> None:
    if metadata.get("networkType") != "Cilium":
        return
    cilium = metadata.get("ciliumDay1", {})
    if not cilium.get("version") or not cilium.get("channel"):
        errors.append("metadata.yaml missing ciliumDay1 version/channel")
    images = cilium.get("images", {})
    for image_key in ("cilium", "operator", "clife"):
        if not images.get(image_key):
            errors.append(f"metadata.yaml missing ciliumDay1.images.{image_key}")

    ciliumconfig_path = data_dir / "manifests" / "ciliumconfig.yaml"
    if not ciliumconfig_path.is_file():
        errors.append(f"missing Cilium Day 1 manifest {ciliumconfig_path}")
        return
    ciliumconfig = load_yaml(ciliumconfig_path)
    spec = ciliumconfig.get("spec", {})
    if spec.get("version") and spec.get("version") != cilium.get("version"):
        errors.append("CiliumConfig spec.version does not match metadata ciliumDay1.version")
    image_map = spec.get("image", {})
    for image_key in ("cilium", "operator", "clife"):
        if image_map.get(image_key) and images.get(image_key) and image_map.get(image_key) != images[image_key]:
            errors.append(f"CiliumConfig {image_key} image does not match metadata ciliumDay1 image")

    network_path = data_dir / "manifests" / "cluster-network-02-config-local.yml"
    if not network_path.is_file():
        errors.append(f"missing OpenShift Network Operator KPR manifest {network_path}")
    else:
        network = load_yaml(network_path)
        network_spec = network.get("spec", {})
        install = load_yaml(data_dir / "install-config.yaml")
        install_networking = install.get("networking", {})
        if network.get("apiVersion") != "operator.openshift.io/v1" or network.get("kind") != "Network":
            errors.append(f"{network_path} must be an operator.openshift.io/v1 Network")
        if network.get("metadata", {}).get("name") != "cluster":
            errors.append(f"{network_path} must target Network.operator/cluster")
        if network_spec.get("networkType") != "Cilium":
            errors.append(f"{network_path} spec.networkType must be Cilium")
        if network_spec.get("deployKubeProxy") is not False:
            errors.append(f"{network_path} spec.deployKubeProxy must be false when kubeProxyReplacement is enabled")
        if network_spec.get("clusterNetwork") != install_networking.get("clusterNetwork"):
            errors.append(f"{network_path} clusterNetwork does not match install-config.yaml")
        if network_spec.get("serviceNetwork") != install_networking.get("serviceNetwork"):
            errors.append(f"{network_path} serviceNetwork does not match install-config.yaml")

    if spec.get("kubeProxyReplacement") is not True:
        errors.append("CiliumConfig spec.kubeProxyReplacement must be true for the selected Day 1 contract")
    if not spec.get("k8sServiceHost") or not spec.get("k8sServicePort"):
        errors.append("CiliumConfig KPR requires spec.k8sServiceHost and spec.k8sServicePort")
    if spec.get("socketLB", {}).get("hostNamespaceOnly") is not True:
        errors.append("CiliumConfig spec.socketLB.hostNamespaceOnly must be true for OpenShift Virtualization compatibility")
    install = load_yaml(data_dir / "install-config.yaml")
    install_cluster_network = install.get("networking", {}).get("clusterNetwork", []) or []
    cilium_ipam = spec.get("ipam", {}).get("operator", {})
    if install_cluster_network:
        if cilium_ipam.get("clusterPoolIPv4PodCIDRList") != [entry.get("cidr") for entry in install_cluster_network]:
            errors.append("CiliumConfig clusterPoolIPv4PodCIDRList does not match install-config.yaml")
        if cilium_ipam.get("clusterPoolIPv4MaskSize") != install_cluster_network[0].get("hostPrefix"):
            errors.append("CiliumConfig clusterPoolIPv4MaskSize does not match install-config.yaml hostPrefix")

    clife_path = data_dir / "manifests" / "apps_v1_deployment_clife-controller-manager.yaml"
    if not clife_path.is_file():
        errors.append(f"missing CLIFE Day 1 manifest {clife_path}")
        return
    clife_deployment = load_yaml(clife_path)
    containers = clife_deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []) or []
    clife_container = next((container for container in containers if container.get("name") == "manager"), None)
    actual_clife_image = clife_container.get("image") if clife_container else None
    if not actual_clife_image:
        errors.append(f"{clife_path} missing manager container image")
    elif images.get("clife") and actual_clife_image != images["clife"]:
        errors.append("CLIFE Deployment image does not match metadata ciliumDay1.images.clife")


def validate_raw_artifacts(data_dir: Path, manifest_path: Path | None, target_root: Path | None,
                           errors: list[str]) -> None:
    if manifest_path is None or target_root is None:
        errors.append("connected action requires --artifact-manifest and --raw-target-root for pristine generated artifacts")
        return
    raw_selected = (target_root / "data" / "openshift" / data_dir.name).resolve()
    selected = data_dir.resolve()
    if selected.is_relative_to(raw_selected) or raw_selected.is_relative_to(selected):
        errors.append("raw target and enriched cluster directory must be separate trees")
        return
    manifest = load_yaml(manifest_path)
    prefix = f"openshift/{data_dir.name}/"
    selected = [(target, entry) for target in manifest.get("targets", [])
                if target.get("targetRoot") == "data" for entry in target.get("files", [])
                if str(entry.get("path", "")).startswith(prefix)]
    expected = {"metadata.yaml", "install-config.yaml", "agent-config.yaml"}
    if load_yaml(data_dir / "metadata.yaml").get("networkType") == "Cilium":
        expected |= {"manifests/ciliumconfig.yaml", "manifests/cluster-network-02-config-local.yml"}
    covered = set()
    for target, entry in selected:
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts:
            errors.append("artifact manifest contains unsafe relative path")
            continue
        path = target_root / target["targetRoot"] / rel
        name = str(rel)[len(prefix):]
        covered.add(name)
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            errors.append(f"raw artifact hash mismatch/missing: {rel}")
        # Only private credential/trust values may differ in install-config.
        if name == "install-config.yaml" and path.is_file() and (data_dir / name).is_file():
            before, after = load_yaml(path), load_yaml(data_dir / name)
            for secret_key in ("pullSecret", "sshKey", "additionalTrustBundle"):
                before.pop(secret_key, None); after.pop(secret_key, None)
            if before != after:
                errors.append("selected install-config non-secret intent differs from verified raw artifact")
        if name == "agent-config.yaml" and path.is_file() and (data_dir / name).is_file():
            if load_yaml(data_dir / "metadata.yaml").get("hardwareInventory") == "declared" and load_yaml(path) != load_yaml(data_dir / name):
                errors.append("selected declared hardware differs from verified raw artifact")
        # Canonical networking/release intent must survive private enrichment intact.
        if (name == "metadata.yaml" or name.startswith("manifests/")) and (data_dir / name).is_file() and path.is_file():
            if path.read_bytes() != (data_dir / name).read_bytes():
                errors.append(f"selected canonical intent differs from verified raw artifact: {name}")
    if not expected <= covered:
        errors.append(f"artifact manifest lacks selected source files: {sorted(expected - covered)}")


def gitops_bootstrap_selection(metadata: dict) -> dict[str, str]:
    """Consume rendered canonical selections; never choose a catalog or trust policy."""
    services = metadata.get("platformServices")
    gitops = services.get("gitops") if isinstance(services, dict) else None
    sub = gitops.get("operatorSubscription") if isinstance(gitops, dict) else None
    if not isinstance(sub, dict):
        raise ValueError("post-install requires platformServices.gitops.operatorSubscription from canonical defaults")
    names = {"name": "NAME", "namespace": "NAMESPACE", "source": "SOURCE", "sourceNamespace": "SOURCE_NAMESPACE"}
    selection = {}
    for key, variable, value in (
        ("repoURL", "GITOPS_REPO_URL", gitops.get("repoURL")),
        ("targetRevision", "GITOPS_TARGET_REVISION", gitops.get("targetRevision")),
        ("gitopsBootstrapPath", "GITOPS_ROOT", metadata.get("gitopsBootstrapPath")),
    ):
        if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
            raise ValueError(f"GitOps {key} must be an explicit single-line value")
        selection[variable] = value
    for key, variable in names.items():
        value = sub.get(key)
        if not isinstance(value, str) or len(value) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
            raise ValueError(f"GitOps operatorSubscription.{key} must be an explicit Kubernetes name")
        selection["GITOPS_OPERATOR_" + variable] = value
    channel, approval = sub.get("channel"), sub.get("installPlanApproval")
    if not isinstance(channel, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", channel):
        raise ValueError("GitOps operatorSubscription.channel is required")
    if approval not in {"Manual", "Automatic"}:
        raise ValueError("GitOps operatorSubscription.installPlanApproval must be Manual or Automatic")
    selection.update(GITOPS_OPERATOR_CHANNEL=channel, GITOPS_OPERATOR_APPROVAL=approval)
    if sub.get("startingCSV") is not None:
        value = sub["startingCSV"]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("invalid declared GitOps startingCSV")
        selection["GITOPS_OPERATOR_STARTING_CSV"] = value
    delivery = metadata.get("imageDelivery", {})
    registry = services.get("registry", "")
    delivery_registry = delivery.get("registry", "")
    if not isinstance(registry, str) or not isinstance(delivery_registry, str) or delivery_registry.rstrip("/") != registry.rstrip("/"):
        raise ValueError("platformServices registry conflicts with imageDelivery registry")
    if delivery.get("mode") == "mirrored" and not registry:
        raise ValueError("mirrored post-install requires its selected registry")
    policy = services.get("registryTrustPolicy", "")
    if not registry:
        if policy:
            raise ValueError("registry trust policy must not be selected without a registry")
        selection.update(GITOPS_REGISTRY_HOST="", GITOPS_REGISTRY_TRUST_POLICY="")
    else:
        parsed = urlsplit("//" + registry)
        parsed.port  # Reject malformed or out-of-range declared ports.
        if not parsed.hostname or parsed.username or parsed.password or parsed.path.strip("/") or parsed.query or parsed.fragment:
            raise ValueError("selected registry must be a credential-free host[:port]")
        if policy not in {"public", "additional-ca"}:
            raise ValueError("selected registry requires explicit public/additional-ca trust policy")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname):
            raise ValueError("registry hostname cannot be used as an Argo TLS ConfigMap key")
        selection.update(GITOPS_REGISTRY_HOST=parsed.hostname, GITOPS_REGISTRY_TRUST_POLICY=policy)
    return selection


def render_gitops_subscription(metadata: dict) -> tuple[dict, dict[str, str]]:
    selection = gitops_bootstrap_selection(metadata)
    template = Path(__file__).resolve().parents[1] / "manifests/argocd/01-subscription.yaml"
    document = yaml.safe_load(Template(template.read_text()).substitute(selection))
    if "GITOPS_OPERATOR_STARTING_CSV" in selection:
        document["spec"]["startingCSV"] = selection["GITOPS_OPERATOR_STARTING_CSV"]
    return document, selection


def validate_gitops_root(metadata: dict, checkout: Path | None, errors: list[str]) -> None:
    """Check an operator-supplied checkout, without fetching or inventing a root."""
    if checkout is None:
        errors.append("post-install requires --gitops-target-root (reviewed customer GitOps checkout)")
        return
    relative = metadata.get("gitopsBootstrapPath", "")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        errors.append("unsafe/missing declared gitopsBootstrapPath")
        return
    services = metadata.get("platformServices")
    selection = services.get("gitops") if isinstance(services, dict) else None
    if not isinstance(selection, dict):
        errors.append("post-install requires declared platformServices.gitops")
        return
    url, revision = selection.get("repoURL"), selection.get("targetRevision")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.hostname or not parsed.path.strip("/") or parsed.username or parsed.password or parsed.query or parsed.fragment or not isinstance(revision, str) or not revision or revision.startswith("-"):
        errors.append("post-install requires declared credential-free HTTPS repoURL and targetRevision")
        return
    def git(*args):
        return subprocess.check_output(["git", "-C", str(checkout), *args], text=True, stderr=subprocess.DEVNULL).strip()
    try:
        if Path(git("rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
            errors.append("gitops-target-root must be the repository checkout root")
        if git("remote", "get-url", "origin").removesuffix(".git") != url.removesuffix(".git"):
            errors.append("GitOps checkout origin conflicts with declared repoURL")
        if git("rev-parse", "HEAD") != git("rev-parse", "--verify", revision + "^{commit}"):
            errors.append("GitOps checkout HEAD conflicts with declared targetRevision")
        if git("status", "--porcelain"):
            errors.append("GitOps checkout has uncommitted/untracked changes")
    except (subprocess.CalledProcessError, OSError):
        errors.append("cannot verify GitOps checkout origin/revision")
        return
    root = (checkout / relative).resolve()
    if not root.is_relative_to(checkout.resolve()):
        errors.append("GitOps root escapes supplied checkout")
        return
    candidates = [root / name for name in ("kustomization.yaml", "kustomization.yml", "Kustomization") if (root / name).is_file()]
    if len(candidates) != 1:
        errors.append("declared customer GitOps root requires exactly one Kustomization")
        return
    try:
        git("ls-files", "--error-unmatch", "--", str(candidates[0].relative_to(checkout.resolve())))
    except subprocess.CalledProcessError:
        errors.append("customer GitOps Kustomization is not tracked in the reviewed checkout")
        return
    document = load_yaml(candidates[0])
    if document.get("kind") != "Kustomization" or document.get("apiVersion") != "kustomize.config.k8s.io/v1beta1" or not isinstance(document.get("resources"), list) or not document["resources"] or any(not isinstance(resource, str) or not resource for resource in document["resources"]):
        errors.append("customer GitOps root must declare a nonempty Kustomization resources list")


def validate_agent_staging(data_dir: Path, errors: list[str]) -> None:
    metadata = load_yaml(data_dir / "metadata.yaml")
    if metadata.get("imageDelivery", {}).get("mode") == "mirrored":
        scopes = ["ocp-install-core"] + (["cilium-day1"] if metadata.get("networkType") == "Cilium" else [])
        for scope in scopes:
            source = bundle_root(data_dir, scope)
            if source is None or not (source / "manifests").is_dir():
                errors.append(f"Agent staging lacks selected {scope} receipt payload")
                continue
            for path in (source / "manifests").glob("*.yaml"):
                staged = data_dir / "manifests" / f"{scope}--{path.name}"
                if not staged.is_file() or staged.read_bytes() != path.read_bytes():
                    errors.append(f"Agent prepared manifests lack exact selected mirror policy {scope}--{path.name}")
    prepared = {p.name: p for p in (data_dir / "manifests").iterdir() if p.suffix in {".yaml", ".yml"}}
    staged = {p.name: p for p in (data_dir / "openshift").glob("*") if p.suffix in {".yaml", ".yml"}}
    if set(prepared) != set(staged):
        errors.append("Agent openshift/ YAML set differs from prepared manifests/; use a fresh staging directory")
    for name in prepared.keys() & staged.keys():
        if prepared[name].read_bytes() != staged[name].read_bytes():
            errors.append(f"Agent openshift/{name} differs from enriched manifests/{name}")


def validate_action(data_dir: Path, action: str, *, artifact_manifest: Path | None = None, raw_target_root: Path | None = None, agent_staging: bool = False, gitops_target_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    metadata, _, _ = validate_common(data_dir, errors)
    if not metadata:
        return errors

    validate_cilium(data_dir, metadata, errors)
    delivery = metadata.get("imageDelivery")
    if not isinstance(delivery, dict) or not {"mode", "scopes", "registry"} <= delivery.keys():
        errors.append("metadata.yaml requires explicit imageDelivery mode/scopes/registry from platform input")
        return errors
    mode, scopes = delivery["mode"], delivery["scopes"]
    if mode not in {"connected", "mirrored"} or not isinstance(scopes, list) or any(not isinstance(v, str) or v not in {*BUNDLE_KEYS, "platform-day2"} for v in scopes) or len(scopes) != len(set(scopes)):
        errors.append("invalid imageDelivery mode/scopes")
        return errors
    if mode == "connected":
        if scopes:
            errors.append("connected delivery must not select mirrored scopes")
        validate_raw_artifacts(data_dir, artifact_manifest, raw_target_root, errors)
    elif action == "deploy":
        required = {"ocp-install-core"} | ({"cilium-day1"} if metadata.get("networkType") == "Cilium" else set())
        if not required <= set(scopes):
            errors.append("mirrored delivery omits required Day1 scopes")
        for scope in sorted(required & set(scopes)):
            validate_bundle(data_dir, scope, errors)
    elif action == "post-install":
        if "gitops-bootstrap" not in scopes:
            errors.append("post-install GitOps requires selected gitops-bootstrap scope")
        else:
            validate_bundle(data_dir, "gitops-bootstrap", errors)
    else:
        raise ValueError(f"unsupported action {action}")
    if action not in {"deploy", "post-install"}:
        raise ValueError(f"unsupported action {action}")
    if action == "post-install":
        try:
            render_gitops_subscription(metadata)
        except ValueError as exc:
            errors.append(str(exc))
        validate_gitops_root(metadata, gitops_target_root, errors)
    if agent_staging:
        validate_agent_staging(data_dir, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster-dir", type=Path, required=True)
    parser.add_argument("--action", choices=["deploy", "post-install"], required=True)
    parser.add_argument("--artifact-manifest", type=Path, help="Raw platform GeneratedArtifactManifest, checked before private enrichment")
    parser.add_argument("--raw-target-root", type=Path, help="Pristine generated compute repo root containing data/")
    parser.add_argument("--gitops-target-root", type=Path, help="Clean reviewed GitOps checkout at declared repoURL/targetRevision, containing gitopsBootstrapPath")
    parser.add_argument("--gitops-output-dir", type=Path, help="Runtime directory for validated subscription.yaml and selection.env; post-install only")
    parser.add_argument("--agent-staging", action="store_true", help="Verify Agent openshift/ exactly matches enriched manifests/")
    args = parser.parse_args()

    if not args.cluster_dir.is_dir():
        print(f"ERROR: missing selected cluster directory {args.cluster_dir}", file=sys.stderr)
        return 1

    errors = validate_action(args.cluster_dir, args.action, artifact_manifest=args.artifact_manifest, raw_target_root=args.raw_target_root, agent_staging=args.agent_staging, gitops_target_root=args.gitops_target_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.gitops_output_dir is not None:
        if args.action != "post-install":
            raise ValueError("--gitops-output-dir requires --action post-install")
        destination = args.gitops_output_dir.resolve()
        protected = [args.cluster_dir, args.raw_target_root, args.gitops_target_root, Path(__file__).resolve().parents[1]]
        if any(destination.is_relative_to(path.resolve()) or path.resolve().is_relative_to(destination) for path in protected if path is not None):
            raise ValueError("GitOps runtime output must be separate from raw, enriched, GitOps and source trees")
        document, selection = render_gitops_subscription(load_yaml(args.cluster_dir / "metadata.yaml"))
        args.gitops_output_dir.mkdir(parents=True, exist_ok=True)
        (args.gitops_output_dir / "subscription.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
        (args.gitops_output_dir / "selection.env").write_text("".join(f"{name}={value}\n" for name, value in sorted(selection.items())))
    print(f"selected cluster contract valid for {args.action}: {args.cluster_dir}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
