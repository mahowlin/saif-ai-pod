# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
"""Offline operation regressions; all external commands are synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


SELECT = module('select_profiles', 'select-ucs-profiles.py')
UNASSIGN = module('unassign_profiles', 'unassign-ucs-profiles.py')
HARDWARE = module('resolve_hardware', 'resolve-agent-hardware.py')


def reply(rows, status=0):
    return subprocess.CompletedProcess(['synthetic-isctl'], status, json.dumps(rows), '')


def profile(state='Associated', moid='synthetic-moid'):
    return [{'Name': 'selected', 'Moid': moid, 'ConfigContext': {'ConfigState': state}}]


class ComputeOperationSafety(unittest.TestCase):
    def test_plan_rejects_domain_mutations_and_workflow_defends_again(self):
        for domain in ('Deployed', 'Unassigned'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                SELECT.select(ROOT / 'ucs/defaults/profiles', 'ALL', 'Plan', domain)
        workflow = yaml.safe_load((ROOT / '.github/workflows/ucs-deploy.yaml').read_text())
        steps = {step['name']: step for step in workflow['jobs']['deploy']['steps']}
        self.assertIn("inputs.operation == 'Stage'", steps['Deploy Domain']['if'])
        self.assertIn("inputs.operation == 'Deactivate'", steps['Unassign Domain']['if'])
        deletion = steps['Prepare Delete (Unassign + Move to Inactive)']['run']
        self.assertLess(deletion.index('unassign-ucs-profiles.py'), deletion.index('git mv'))
        self.assertTrue(deletion.lstrip().startswith('set -euo pipefail'))

    def test_inventory_owns_filenames_and_unknown_profile_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'active').mkdir()
            (root / 'active/unrelated-name.ezi.yaml').write_text(
                'org:\n  profiles:\n    server:\n      - name: chosen-server\n')
            names, files = SELECT.select(root, 'ALL', 'Plan', 'Unchanged')
            self.assertEqual(names, ['chosen-server'])
            self.assertEqual(files, {'chosen-server': 'unrelated-name.ezi.yaml'})
            with self.assertRaises(ValueError):
                SELECT.select(root, 'missing', 'Delete', 'Unchanged')
        names, files = SELECT.select(ROOT / 'ucs/defaults/profiles', 'ALL', 'Plan', 'Unchanged')
        self.assertEqual(set(names), set(files))
        self.assertTrue(names)

    def test_failed_or_uncertain_unassignment_cannot_succeed(self):
        cases = [reply([], 1), reply({}), reply(profile() * 2),
                 reply([{'Name': 'selected', 'Moid': 'm'}]),
                 reply(profile('Unknown'))]
        for observed in cases:
            with self.subTest(observed=observed.stdout), patch.object(
                    UNASSIGN.subprocess, 'run', return_value=observed) as command:
                with self.assertRaises(RuntimeError):
                    UNASSIGN.unassign(['selected'])
                self.assertEqual(command.call_count, 1)
        with patch.object(UNASSIGN.subprocess, 'run', side_effect=[reply(profile()), reply([], 1)]):
            with self.assertRaisesRegex(RuntimeError, 'unassignment failed'):
                UNASSIGN.unassign(['selected'])

    def test_poll_disappearance_failure_timeout_and_success(self):
        for final in ([], profile('Failed'), profile('Not-assigned', 'different')):
            with self.subTest(final=final), patch.object(UNASSIGN.subprocess, 'run',
                    side_effect=[reply(profile()), reply([]), reply(final)]):
                with self.assertRaises(RuntimeError):
                    UNASSIGN.unassign(['selected'])
        with patch.object(UNASSIGN.subprocess, 'run', side_effect=[reply(profile()), reply([])]):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                UNASSIGN.unassign(['selected'], wait=0)
        with patch.object(UNASSIGN.subprocess, 'run', side_effect=[
                reply(profile()), reply([]), reply(profile('Not-assigned'))]):
            UNASSIGN.unassign(['selected'])
        with patch.object(UNASSIGN.subprocess, 'run', return_value=reply([])) as command:
            UNASSIGN.unassign(['selected'])
            self.assertEqual(command.call_count, 1)

    def test_install_guard_blocks_unknown_and_cleans_owned_key(self):
        source = ROOT / 'scripts/check-cluster-before-install.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ssh = root / 'ssh'
            ssh.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                           'sys.stdin.read()\n'
                           'open(os.environ["CALLS"],"w").write(json.dumps(sys.argv[1:]))\n'
                           'sys.exit(int(os.environ["SSH_STATUS"]))\n')
            ssh.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       CLUSTER_IP='192.0.2.10', SSH_PRIVATE_KEY='synthetic-key',
                       RUNNER_TEMP=directory, CALLS=str(root / 'calls'),
                       SSH_PROXY_JUMP='jump@jump.example.test')
            for status in (0, 10, 11, 255):
                with self.subTest(status=status):
                    result = subprocess.run(['bash', str(source)], env=dict(env, SSH_STATUS=str(status)),
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode == 0, status == 10)
                    self.assertEqual(list(root.glob('install-observation.*')), [])
                    args = json.loads((root / 'calls').read_text())
                    self.assertIn('StrictHostKeyChecking=yes', args)
                    self.assertNotIn('synthetic-key', ' '.join(args))
                    self.assertIn('jump@jump.example.test', args)

    def test_disk_discovery_rejects_changed_assignment_and_ambiguous_drives(self):
        selected = {'AssignedServer': {'Moid': 'server-id', 'ObjectType': 'compute.Blade'}}
        with patch.object(HARDWARE, 'run_isctl', return_value=[
                {'Moid': 'server-id', 'Serial': 'OTHER'}]) as command:
            with self.assertRaises(SystemExit):
                HARDWARE.boot_disk_hint(selected, 'DECLARED')
            self.assertEqual(command.call_count, 1)
        with patch.object(HARDWARE, 'run_isctl', return_value=[
                {'Model': 'DATA RAID', 'Ancestors': [{'Moid': 'server-id'}]}, {'Model': 'BOOT RAID', 'Ancestors': [{'Moid': 'server-id'}]}]):
            with self.assertRaises(SystemExit):
                HARDWARE.virtual_drive_hint('server-id')
        with patch.object(HARDWARE, 'run_isctl', return_value=[
                {'Moid': 'a', 'Model': 'M.2', 'Serial': 'A', 'Ancestors': [{'Moid': 'server-id'}]},
                {'Moid': 'b', 'Model': 'M.2', 'Serial': 'B', 'Ancestors': [{'Moid': 'server-id'}]}]):
            with self.assertRaises(SystemExit):
                HARDWARE.physical_disk_hint('server-id', 'DECLARED')

    def test_hardware_requires_unique_profile_and_vnic(self):
        with patch.object(HARDWARE, 'run_isctl', return_value=[
                {'Name': 'selected'}, {'Name': 'selected'}]):
            with self.assertRaises(SystemExit):
                HARDWARE.profile_data('selected')
        with patch.object(HARDWARE, 'run_isctl', return_value=[
                {'Name': 'eth0', 'MacAddress': '00:11:22:33:44:55'},
                {'Name': 'eth0', 'MacAddress': '00:11:22:33:44:66'}]):
            with self.assertRaises(SystemExit):
                HARDWARE.mac_address('profile-id', 'eth0')

    def test_private_handoff_preflight_runs_before_any_deployment(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/openshift-pipeline.yaml').read_text())
        script = workflow['jobs']['preflight']['steps'][0]['run']
        self.assertIn('preflight', workflow['jobs']['deploy']['needs'])
        self.assertIn("needs.preflight.result == 'success'", workflow['jobs']['deploy']['if'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for key in ('cluster_dir', 'artifact_manifest', 'raw_target_root', 'gitops_target_root'):
                (path / key).touch() if key == 'artifact_manifest' else (path / key).mkdir()
            for contract, success in (({}, False),
                    ({key: str(path / key) for key in ('cluster_dir', 'artifact_manifest', 'raw_target_root', 'gitops_target_root')}, True)):
                env = dict(os.environ, POST_INSTALL='true', POST_INSTALL_CONTRACT=json.dumps(contract))
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_explicit_kubeconfig_path_requires_no_repository_or_token(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/openshift-test.yaml').read_text())
        script = next(step['run'] for step in workflow['jobs']['test']['steps'] if step['name'] == 'Setup Kubeconfig')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            supplied = path / 'caller-owned'
            supplied.write_text('synthetic caller input')
            output = path / 'env'
            env = dict(os.environ, PROVIDED_KUBECONFIG=str(supplied), GITHUB_ENV=str(output),
                       KUBECONFIG_REPO_TOKEN='', KUBECONFIG_REPOSITORY='')
            result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(supplied), output.read_text())
            self.assertEqual(supplied.read_text(), 'synthetic caller input')

    def test_domain_identity_is_declared_and_ambiguous_selection_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'domain.ezi.yaml').write_text('org:\n  profiles:\n    domain:\n      - name: recipient-domain\n')
            self.assertEqual(SELECT.domain_profile(root), 'recipient-domain')
            (root / 'second.ezi.yaml').write_text('org:\n  profiles:\n    domain:\n      - name: other-domain\n')
            with self.assertRaises(ValueError):
                SELECT.domain_profile(root)
        workflow = yaml.safe_load((ROOT / '.github/workflows/ucs-deploy.yaml').read_text())
        for step in workflow['jobs']['deploy']['steps']:
            if step.get('name') in {'Deploy Domain', 'Unassign Domain'}:
                self.assertIn('${DOMAIN_PROFILE}', step['run'])
                self.assertIn("steps.profiles.outputs.domain", step['env']['DOMAIN_PROFILE'])


if __name__ == '__main__':
    unittest.main()
