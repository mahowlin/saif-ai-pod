# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
"""Exercise actual contract methods with synthetic observations, without a cluster."""
import ast
import ipaddress
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def source_methods(filename):
    tree = ast.parse((ROOT / 'tests' / filename).read_text())
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    for node in selected:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    namespace = {'re': re, 'ipaddress': ipaddress, 'Path': Path}
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, 'exec'), namespace)
    return namespace


CONTRACT = source_methods('test_cluster_contract.py')
FIXTURES = source_methods('conftest.py')


def request():
    return SimpleNamespace(node=SimpleNamespace(user_properties=[]))


class RequiredObservations(unittest.TestCase):
    def test_missing_or_error_operators_are_not_healthy(self):
        check = CONTRACT['TestCluster']().test_clusteroperators_available
        for state in ({}, {'clusteroperators': {'items': []}}, {'clusteroperators': {'error': 'synthetic failure'}}):
            with self.subTest(state=state), self.assertRaises(AssertionError):
                check({}, state, request())
        healthy = {'clusteroperators': {'items': [{'metadata': {'name': 'synthetic'}, 'status': {
            'conditions': [{'type': 'Available', 'status': 'True'},
                           {'type': 'Progressing', 'status': 'False'},
                           {'type': 'Degraded', 'status': 'False'}]}}]}}
        check({}, healthy, request())

    def test_ntp_requires_observation_for_every_node(self):
        check = CONTRACT['TestChrony']().test_ntp_synchronized
        nodes = {'items': [{'metadata': {'name': 'worker-a'}}, {'metadata': {'name': 'worker-b'}}]}
        for ntp in ({}, {'worker-a': {'timedatectl': 'yes'}}, {'worker-a': {}, 'worker-b': {}}):
            with self.subTest(ntp=ntp), self.assertRaises(AssertionError):
                check({'nodes': nodes, 'ntp': ntp}, request())
        check({'nodes': nodes, 'ntp': {name: {'timedatectl': 'yes'} for name in ('worker-a', 'worker-b')}}, request())

    def test_mirror_authority_comes_from_declared_metadata(self):
        check = CONTRACT['TestDisconnectedImagePolicy']().test_idms_mirrors_use_local_registry
        metadata = {'capabilities': ['disconnectedCatalogs'], 'imageDelivery': {'registry': 'changed.example.test:5443'}}
        snapshot = {'idms': {'items': [{'spec': {'imageDigestMirrors': [{'mirrors': ['changed.example.test:5443/team/image']}]}}]}}
        check(metadata, snapshot, request())
        snapshot['idms']['items'][0]['spec']['imageDigestMirrors'][0]['mirrors'] = ['changed.example.test:5443.evil/team/image']
        with self.assertRaises(AssertionError):
            check(metadata, snapshot, request())

    def test_management_interface_comes_from_declared_default_route(self):
        hosts = {'hosts': [{'hostname': 'worker-a.example.test', 'role': 'master', 'networkConfig': {
            'interfaces': [{'name': 'uplink9', 'ipv4': {'address': [{'ip': '192.0.2.10'}]}}],
            'routes': {'config': [{'destination': '0.0.0.0/0', 'next-hop-interface': 'uplink9'}]}}}]}
        self.assertEqual(FIXTURES['_node_intents']({}, hosts)[0]['ip'], '192.0.2.10')
        hosts['hosts'][0]['networkConfig']['routes']['config'] = []
        with self.assertRaises(AssertionError):
            FIXTURES['_node_intents']({}, hosts)


if __name__ == '__main__':
    unittest.main()
