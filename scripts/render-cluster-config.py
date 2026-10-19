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
OpenShift cluster config renderer — unified code path.

Loads a cluster definition from openshift/clusters/<name>.yaml, reads
cluster.mode to select templates from openshift/modes/<mode>/templates/,
and renders intent-only OpenShift artifacts. Hardware facts are resolved later
from live Intersight data during OpenShift validation.
"""

import os
import sys
import shutil
import base64
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def b64encode_filter(value):
    """Jinja2 filter to base64 encode a string for Ignition data URLs."""
    if isinstance(value, str):
        value = value.encode('utf-8')
    return base64.b64encode(value).decode('ascii')


def render(cluster_name, dry_run=False, output_dir=None, inject_secrets=False):
    """Render config for any cluster using the unified data model.

    Single code path: load cluster def → read mode → enrich nodes → render.
    """
    warnings = []

    # Load cluster definition
    cluster_def_file = Path(f"openshift/clusters/{cluster_name}.yaml")
    if not cluster_def_file.exists():
        print(f"❌ Cluster definition not found: {cluster_def_file}")
        available = [f.stem for f in Path("openshift/clusters").glob("*.yaml")]
        print(f"   Available clusters: {', '.join(sorted(available)) or 'none'}")
        sys.exit(1)

    with open(cluster_def_file) as f:
        data = yaml.safe_load(f)

    cluster = data.get('cluster', {})
    infrastructure = data.get('infrastructure', {})

    if not cluster or not infrastructure:
        print(f"❌ Invalid cluster definition: missing 'cluster' or 'infrastructure' section")
        sys.exit(1)

    mode = cluster.get('mode', '')
    nodes = cluster.get('nodes', [])
    print(f"Rendering {mode} config for {cluster_name} ({len(nodes)} node{'s' if len(nodes) != 1 else ''})...")

    # Verify template directory exists
    template_dir = Path(f"openshift/modes/{mode}/templates")
    if not template_dir.exists():
        print(f"❌ Template directory not found: {template_dir}")
        sys.exit(1)

    # Hardware facts are resolved from live Intersight data during validation.
    # The renderer intentionally emits placeholders so users do not need to know
    # MAC addresses or boot disk hints when defining cluster intent.
    for i, node in enumerate(nodes):
        if not node.get('ucs_profile', ''):
            warnings.append(f"Node {i} ({node.get('hostname', 'unknown')}): missing ucs_profile")
        node['mac_eth0'] = 'MAC_PLACEHOLDER'
        node['mac_eth1'] = 'MAC_PLACEHOLDER'
        node['boot_disk_model'] = 'BOOT_DISK_MODEL_PLACEHOLDER'

    # Setup Jinja2
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters['b64encode'] = b64encode_filter

    context = {
        'cluster': cluster,
        'infrastructure': infrastructure,
    }

    # Inject secrets if requested
    if inject_secrets:
        pull_secret = os.environ.get('REDHAT_PULL_SECRET', '')
        ssh_key = os.environ.get('SSH_PUBLIC_KEY', '')
        additional_trust_bundle = os.environ.get('REGISTRY_CA_CERT', '')

        if not pull_secret:
            warnings.append("REDHAT_PULL_SECRET environment variable not set")
        if not ssh_key:
            warnings.append("SSH_PUBLIC_KEY environment variable not set")

        context['pull_secret'] = pull_secret
        context['ssh_key'] = ssh_key
        context['additional_trust_bundle'] = additional_trust_bundle
        print(f"  🔐 Injecting secrets from environment variables")

    # Output directory
    if output_dir is None:
        output_dir = f"openshift/data/{cluster_name}"
    os.makedirs(output_dir, exist_ok=True)

    # Render install-config and agent-config templates
    for template_name in ['install-config.yaml.j2', 'agent-config.yaml.j2']:
        try:
            template = env.get_template(template_name)
            rendered = template.render(context)
            output_file = template_name.replace('.j2', '')

            if dry_run:
                print(f"\n=== {output_file} for {cluster_name} ===")
                print(rendered)
            else:
                with open(f'{output_dir}/{output_file}', 'w') as f:
                    f.write(rendered)
                print(f"✅ Wrote {output_dir}/{output_file}")
        except Exception as e:
            warnings.append(f"Failed to render {template_name}: {str(e)}")

    # Render Day 1 manifests (common + mode-specific)
    if not dry_run:
        common_manifest_dir = Path("openshift/modes/common/manifests")
        mode_manifest_dir = template_dir / "manifests"

        # Collect manifest source directories (common first, then mode-specific)
        manifest_dirs = []
        if common_manifest_dir.exists():
            manifest_dirs.append(("common", common_manifest_dir))
        if mode_manifest_dir.exists():
            manifest_dirs.append((mode, mode_manifest_dir))

        if manifest_dirs:
            manifests_dir = Path(output_dir) / "manifests"
            manifests_dir.mkdir(parents=True, exist_ok=True)

            # Storage host preparation is a Day-2 GitOps concern selected by
            # the canonical SAIF topology profile. AI Pod renders only install
            # and bootstrap manifests.
            manifest_context = {**context}

            print(f"\n🔧 Rendering Day 1 manifests for {cluster_name}:")

            # Track rendered files (mode-specific overrides common)
            templated_files = set()

            for source_label, manifest_template_dir in manifest_dirs:
                manifest_env = Environment(
                    loader=FileSystemLoader(str(manifest_template_dir)),
                    trim_blocks=True,
                    lstrip_blocks=True,
                )
                manifest_env.filters['b64encode'] = b64encode_filter

                # Process .j2 templates
                for template_file in sorted(manifest_template_dir.glob("*.j2")):
                    try:
                        template = manifest_env.get_template(template_file.name)
                        rendered = template.render(manifest_context)
                        output_file = manifests_dir / template_file.stem
                        with open(output_file, 'w') as f:
                            f.write(rendered)
                        print(f"  ✅ {output_file.name} ({source_label})")
                        templated_files.add(template_file.stem)
                    except Exception as e:
                        warnings.append(f"Failed to render manifest {template_file.name}: {str(e)}")

                # Copy static manifests (skip if .j2 version exists)
                for manifest_file in sorted(
                    list(manifest_template_dir.glob("*.yaml"))
                    + list(manifest_template_dir.glob("*.yml"))
                ):
                    if manifest_file.name in templated_files:
                        continue
                    output_file = manifests_dir / manifest_file.name
                    shutil.copy2(manifest_file, output_file)
                    print(f"  📋 {output_file.name} ({source_label}, copied)")
                    templated_files.add(manifest_file.name)

    # Report warnings
    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")
        print(f"\n❌ Rendering completed with warnings. Review and fix the issues above.")
        sys.exit(1)
    else:
        if not dry_run:
            print(f"\n✅ Rendered {mode} config for {cluster_name} successfully")


def main():
    print("Retired standalone Compute renderer CLI. Use canonical Datacenter render and manifest handoff; see agents/installation.md in this repository.", file=sys.stderr)
    raise SystemExit(2)


if __name__ == '__main__':
    main()
