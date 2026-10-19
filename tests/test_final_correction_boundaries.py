"""Assigned observation and actual workflow producer/private cleanup regressions."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hardware', ROOT/'scripts/resolve-agent-hardware.py')
hardware = importlib.util.module_from_spec(spec); spec.loader.exec_module(hardware)


def step(file, name):
    document = yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
    return next(s for j in document['jobs'].values() for s in j['steps'] if s.get('name') == name)


def script(value):
    return re.sub(r'\$\{\{\s*vars\.(\w+)\s*\}\}', lambda m: '${'+m[1]+'}', value).replace('${{ github.run_id }}','fixture')


class FinalBoundaries(unittest.TestCase):
    def test_incomplete_assigned_disk_observation_fails(self):
        for drives in ([{'Model':'DATA_RAID'},{}],[{}],[{'Model':' '} ]):
            rows=[dict(d,Ancestors=[{'Moid':'assigned'}]) for d in drives]
            with self.subTest(rows=rows),patch.object(hardware,'run_isctl',return_value=rows),self.assertRaises(SystemExit):
                hardware.virtual_drive_hint('assigned')
        with patch.object(hardware,'run_isctl',return_value=[{'Ancestors':[{'Moid':'assigned'}], 'Model':'M.2'}]),self.assertRaises(SystemExit):
            hardware.physical_disk_hint('assigned','serial')

    def test_kubeconfig_writer_uses_nondefault_ref_and_cleans_private_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); remote=root/'remote.git'; seed=root/'seed'
            def git(*args,cwd=None):
                return subprocess.run(['git',*args],cwd=cwd,check=True,capture_output=True,text=True).stdout
            git('init','--bare',str(remote));git('init',str(seed));git('config','user.name','test',cwd=seed);git('config','user.email','test@example.org',cwd=seed)
            (seed/'README').write_text('fixture');git('add','.',cwd=seed);git('commit','-m','fixture',cwd=seed);git('branch','-M','main',cwd=seed);git('remote','add','origin',str(remote),cwd=seed);git('push','origin','main',cwd=seed);git('checkout','-b','selected-ref',cwd=seed);git('push','origin','selected-ref',cwd=seed)
            realgit=shutil.which('git');bin_dir=root/'bin';bin_dir.mkdir();wrapper=bin_dir/'git'
            wrapper.write_text('#!'+sys.executable+'\nimport sys,os\na=sys.argv[1:]\na=[os.environ["FIXTURE_REMOTE"] if x.startswith("https://github.com/") else x for x in a]\nos.execv('+repr(realgit)+',['+repr(realgit)+',*a])\n');wrapper.chmod(0o755)
            runtime=root/'runtime';runtime.mkdir();kube=root/'kube';kube.write_text('synthetic-kubeconfig')
            env=dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],FIXTURE_REMOTE=str(remote),RUNNER_TEMP=str(runtime),GITHUB_STEP_SUMMARY=str(root/'summary'),CLUSTER='selected',KUBECONFIG=str(kube),KUBECONFIG_REPO_TOKEN='synthetic',KUBECONFIG_REPOSITORY='fixture/configs',KUBECONFIG_REF='selected-ref')
            result=subprocess.run(['bash','-euo','pipefail','-c',script(step('openshift-post-install.yaml','Commit Kubeconfig to Repo')['run'])],env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(git('--git-dir',str(remote),'show','selected-ref:clusters/selected/kubeconfig').strip(),'synthetic-kubeconfig')
            self.assertNotEqual(subprocess.run(['git','--git-dir',str(remote),'cat-file','-e','main:clusters/selected/kubeconfig'],capture_output=True).returncode,0)
            self.assertEqual(list(runtime.iterdir()),[])
            for reader in ['openshift-test.yaml','openshift-undeploy.yaml']:
                text=(ROOT/'.github/workflows'/reader).read_text()
                self.assertIn('--branch "$KUBECONFIG_REF"',text)
                self.assertIn('vars.KUBECONFIG_REPOSITORY',text)

    def test_legacy_cli_fails_without_rendering(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/render-cluster-config.py'),'fixture'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2,result.stderr)
        procedure='agents/installation.md' if (ROOT/'agents/installation.md').exists() else 'docs/agents/compute-operation-safety.md'
        self.assertIn(procedure,result.stderr)
        self.assertTrue((ROOT/procedure).is_file())

    def test_prerequisite_auth_removed_after_failed_network_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bin_dir=root/'bin';bin_dir.mkdir()
            for name,body in [('jq','exit 97'),('curl','exit 98')]:
                p=bin_dir/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            env=dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],RUNNER_TEMP=str(root),GITHUB_STEP_SUMMARY=str(root/'summary'),REDHAT_PULL_SECRET='{"auths":{}}')
            subprocess.run(['bash','-euo','pipefail','-c',step('validate-prerequisites.yaml','Test Red Hat Registry Authentication')['run']],env=env,capture_output=True,text=True)
            self.assertEqual(list(root.glob('prerequisite-auth.*')),[])

    def test_install_wait_key_removed_on_ordinary_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bin_dir=root/'bin';bin_dir.mkdir()
            for name,body in [('yq','echo 192.0.2.5'),('ssh','exit 255'),('sleep','exit 1')]:
                p=bin_dir/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            env=dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],RUNNER_TEMP=str(root),GITHUB_STEP_SUMMARY=str(root/'summary'),SSH_PRIVATE_KEY='synthetic',CLUSTER='selected')
            result=subprocess.run(['bash','-euo','pipefail','-c',step('openshift-deploy.yaml','Wait for Installation Complete')['run']],env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(list(root.glob('install-wait-key.*')),[])

if __name__=='__main__':unittest.main()
