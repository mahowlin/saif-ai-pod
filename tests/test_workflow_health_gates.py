# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
"""Actual workflow health steps with synthetic oc/yq responses; no cluster access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/openshift-test.yaml').read_text())
STEPS = {step.get('name'): step.get('run', '') for step in WORKFLOW['jobs']['test']['steps']}


class WorkflowHealthGates(unittest.TestCase):
    def run_step(self, name, state, success, **extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oc = root / 'oc'
            oc.write_text('#!' + sys.executable + '\nimport os,sys\n'
                          'args=sys.argv[1:]\n'
                          'if args[:2]==["get","namespace"]:sys.exit(0)\n'
                          'if args[:2]==["get","pods"] and "-o" in args and args[args.index("-o")+1]=="name":print("pod/synthetic");sys.exit(0)\n'
                          'if args[:1]==["rsh"]:print(os.environ.get("ETCD_HEALTH",""));sys.exit(int(os.environ.get("ETCD_STATUS","0")))\n'
                          'print(os.environ["STATE_JSON"])\n')
            oc.chmod(0o755)
            yq = root / 'yq'
            yq.write_text('#!/bin/sh\ncase "$*" in *networkType*) echo Cilium;; *) echo true;; esac\n')
            yq.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       STATE_JSON=json.dumps(state), GITHUB_STEP_SUMMARY=str(root / 'summary'), **extra)
            script = STEPS[name].replace('${{ inputs.cluster_name }}', 'synthetic')
            result = subprocess.run(['bash', '-eo', 'pipefail', '-c', script],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_machine_pool_empty_degraded_and_ready(self):
        for rows, success in (([], False),
                ([{'status': {'conditions': [{'type': 'Updated', 'status': 'True'},
                                             {'type': 'Degraded', 'status': 'True'}],
                              'readyMachineCount': 3, 'machineCount': 3}}], False),
                ([{'status': {'conditions': [{'type': 'Updated', 'status': 'True'},
                                             {'type': 'Degraded', 'status': 'False'}],
                              'readyMachineCount': 3, 'machineCount': 3}}], True)):
            with self.subTest(success=success, rows=rows):
                self.run_step('Test MachineConfigPools', {'items': rows}, success)

    def test_cilium_required_empty_and_not_ready_are_failures(self):
        for rows, success in (([], False),
                ([{'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}}], False),
                ([{'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}], True)):
            with self.subTest(success=success, rows=rows):
                self.run_step('Test Cilium CNI', {'items': rows}, success)

    def test_catalog_missing_connecting_and_ready(self):
        for rows, success in (([], False),
                ([{'status': {'connectionState': {'lastObservedState': 'CONNECTING'}}}], False),
                ([{'status': {'connectionState': {'lastObservedState': 'READY'}}}], True)):
            with self.subTest(success=success, rows=rows):
                self.run_step('Test CatalogSources', {'items': rows}, success)

    def test_etcd_failure_and_partial_health_do_not_pass(self):
        for health, status, success in (('endpoint is healthy', '1', False),
                ('endpoint-a is healthy\nendpoint-b failed', '0', False),
                ('endpoint-a is healthy\nendpoint-b is healthy', '0', True)):
            with self.subTest(health=health, status=status):
                self.run_step('Test etcd Health', {}, success, ETCD_HEALTH=health, ETCD_STATUS=status)


if __name__ == '__main__':
    unittest.main()
