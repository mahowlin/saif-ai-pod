#!/usr/bin/env python3
"""Render selected Cilium/CLIFE Day 1 manifests from AI Pod templates."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import io
import tarfile
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader


def load_yaml(path: Path) -> dict:
    with path.open() as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML document in {path}")
    return data


def cluster_context(cluster_dir: Path) -> dict:
    metadata = load_yaml(cluster_dir / "metadata.yaml")
    install_config = load_yaml(cluster_dir / "install-config.yaml")
    cluster_name = metadata.get("clusterName") or cluster_dir.name
    base_domain = install_config.get("baseDomain")
    cluster_network = (install_config.get("networking", {}).get("clusterNetwork") or [{}])[0]
    if not base_domain:
        raise ValueError(f"missing baseDomain in {cluster_dir / 'install-config.yaml'}")
    if not cluster_network.get("cidr") or not cluster_network.get("hostPrefix"):
        raise ValueError(f"missing clusterNetwork cidr/hostPrefix in {cluster_dir / 'install-config.yaml'}")
    return {
        "cluster": {
            "name": cluster_name,
            "network_type": metadata.get("networkType"),
            "release_ref": metadata.get("releaseRef"),
        },
        "infrastructure": {
            "base_domain": base_domain,
            "cluster_network": {
                "cidr": cluster_network["cidr"],
                "host_prefix": cluster_network["hostPrefix"],
            },
        },
        "metadata": metadata,
    }


def verified_bundle_yaml(archive_path: Path, bundle_dir: Path, metadata: dict) -> dict[str, bytes]:
    """Consume only bytes from the verified archive; directory is a checked view."""
    expected = metadata.get("ciliumDay1", {}).get("manifestArchive", {}).get("sha256")
    archive_bytes = archive_path.read_bytes()
    if not expected or hashlib.sha256(archive_bytes).hexdigest() != expected:
        raise ValueError("official archive SHA-256 conflicts with selected metadata")
    sources = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.suffix not in {".yaml", ".yml"}:
                continue
            if not member.isfile() or path.is_absolute() or ".." in path.parts or path.name in sources:
                raise ValueError("official archive requires unique regular YAML filenames and safe relative paths")
            sources[path.name] = archive.extractfile(member).read()
    actual = {p.name: p.read_bytes() for p in bundle_dir.iterdir() if p.suffix in {".yaml", ".yml"} and p.is_file()}
    if not sources or sources != actual:
        raise ValueError("bundle directory YAML bytes/set differ from verified archive")
    return sources


def render_manifests(repo_root: Path, cluster_dir: Path, *, bundle_dir: Path | None = None, bundle_archive: Path | None = None) -> int:
    context = cluster_context(cluster_dir)
    if context["cluster"].get("network_type") != "Cilium":
        return 0

    if bundle_dir is not None:
        # Use the site's verified exact-version official bundle; retain the canonical
        # CiliumConfig and Network intent instead of rendering a second configuration.
        metadata = context["metadata"]
        output_dir = cluster_dir / "manifests"
        output_dir.mkdir(parents=True, exist_ok=True)
        cilium = load_yaml(output_dir / "ciliumconfig.yaml")
        endpoint = cilium["spec"]["k8sServiceHost"]
        port = str(cilium["spec"]["k8sServicePort"])
        expected_image = metadata["ciliumDay1"]["images"]["clife"]
        if bundle_archive is None:
            raise ValueError("official bundle requires its declared checksum-verified archive")
        sources = verified_bundle_yaml(bundle_archive, bundle_dir, metadata)
        documents = []
        deployment_seen = False
        subscription_seen = False
        for source_name, source_bytes in sorted(sources.items()):
            docs = list(yaml.safe_load_all(source_bytes))
            kept = []
            output_name = source_name
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if doc.get("kind") == "CiliumConfig" or (doc.get("kind") == "Network" and doc.get("metadata", {}).get("name") == "cluster"):
                    continue
                if doc.get("kind") == "Deployment" and doc.get("metadata", {}).get("name") == "clife-controller-manager":
                    containers = doc["spec"]["template"]["spec"]["containers"]
                    manager = next((c for c in containers if c.get("name") == "manager"), None)
                    if manager is None or manager.get("image", "").split("@", 1)[0] != expected_image.split("@", 1)[0]:
                        raise ValueError("verified CLife bundle manager image does not match the selected metadata release")
                    if "@" in manager["image"] and manager["image"] != expected_image:
                        raise ValueError("verified CLife bundle manager digest conflicts with selected metadata")
                    manager["image"] = expected_image
                    env = [e for e in manager.get("env", []) if e.get("name") not in {"KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"}]
                    manager["env"] = env + [{"name": "KUBERNETES_SERVICE_HOST", "value": endpoint}, {"name": "KUBERNETES_SERVICE_PORT", "value": port}]
                    deployment_seen = True
                    documents.append(("apps_v1_deployment_clife-controller-manager.yaml", [doc]))
                    continue
                if doc.get("kind") == "Subscription" and doc.get("metadata", {}).get("name") == "clife":
                    if doc.get("spec", {}).get("channel") not in (None, metadata["ciliumDay1"]["channel"]):
                        raise ValueError("verified CLife Subscription channel conflicts with selected metadata")
                    config = doc.setdefault("spec", {}).setdefault("config", {})
                    env = [e for e in config.get("env", []) if e.get("name") not in {"KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"}]
                    config["env"] = env + [{"name": "KUBERNETES_SERVICE_HOST", "value": endpoint}, {"name": "KUBERNETES_SERVICE_PORT", "value": port}]
                    subscription_seen = True
                    documents.append(("subscription.yaml", [doc]))
                    continue
                kept.append(doc)
            if kept:
                documents.append((output_name, kept))
        if not deployment_seen or not subscription_seen:
            raise ValueError("verified CLife bundle requires its manager Deployment and clife Subscription")
        if metadata.get("ocpVersion", "").startswith("4.22.") and not any(
            d.get("kind") == "NetworkPolicy" and d.get("metadata", {}).get("name") == "dns-default-all-egress" and d.get("metadata", {}).get("namespace") == "openshift-dns"
            for _, docs in documents for d in docs
        ):
            raise ValueError("OpenShift4.22 requires the qualified CLife bundle DNS egress policy")
        names = [name for name, _ in documents]
        if len(names) != len(set(names)):
            raise ValueError("verified CLife bundle has conflicting normalized filenames/objects")
        for name, docs in documents:
            (output_dir / name).write_text(yaml.safe_dump_all(docs, sort_keys=False))
        return len(documents)

    source_dir = repo_root / "openshift" / "isovalent-manifests"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"missing Cilium Day 1 source directory: {source_dir}")

    output_dir = cluster_dir / "manifests"
    output_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(source_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    templated_manifest_names = {
        "apps_v1_deployment_clife-controller-manager.yaml.j2",
        "subscription.yaml.j2",
    }
    static_manifest_names = {
        "apiextensions.k8s.io_v1_customresourcedefinition_ciliumconfigs.cilium.io.yaml",
        "operatorgroup.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-ciliumconfig-admin-role.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-ciliumconfig-editor-role.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-ciliumconfig-viewer-role.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-manager-role.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-metrics-auth-role.yaml",
        "rbac.authorization.k8s.io_v1_clusterrole_clife-metrics-reader.yaml",
        "rbac.authorization.k8s.io_v1_clusterrolebinding_clife-manager-rolebinding.yaml",
        "rbac.authorization.k8s.io_v1_clusterrolebinding_clife-metrics-auth-rolebinding.yaml",
        "rbac.authorization.k8s.io_v1_role_clife-leader-election-role.yaml",
        "rbac.authorization.k8s.io_v1_rolebinding_clife-leader-election-rolebinding.yaml",
        "v1_namespace_cilium.yaml",
        "v1_service_clife-metrics.yaml",
        "v1_serviceaccount_clife-controller-manager.yaml",
    }

    written = 0
    for template_name in sorted(templated_manifest_names):
        template = env.get_template(template_name)
        output_path = output_dir / template_name.removesuffix(".j2")
        output_path.write_text(template.render(context))
        written += 1

    for static_name in sorted(static_manifest_names):
        shutil.copy2(source_dir / static_name, output_dir / static_name)
        written += 1

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--bundle-dir", type=Path, help="Private verified exact-version CLife manifest archive directory")
    parser.add_argument("--bundle-archive", type=Path, help="Official archive whose SHA-256 must match selected metadata before staging --bundle-dir")
    args = parser.parse_args()

    cluster_dir = args.cluster_dir
    if not cluster_dir.is_dir():
        raise FileNotFoundError(f"missing selected cluster directory: {cluster_dir}")
    if args.bundle_dir and args.bundle_archive is None:
        parser.error("--bundle-dir requires --bundle-archive")
    if args.bundle_archive and args.bundle_dir is None:
        parser.error("--bundle-archive requires --bundle-dir")
    written = render_manifests(args.repo_root, cluster_dir, bundle_dir=args.bundle_dir, bundle_archive=args.bundle_archive)
    print(f"enriched Cilium Day 1 manifests: {written} file(s) in {cluster_dir / 'manifests'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
