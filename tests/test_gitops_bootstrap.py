"""Exercise the existing bootstrap Bash and Subscription with isolated local tool doubles.

No oc executable, cluster, credentials, network, workflow dispatch or sleep is used.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import yaml
import test_portable_install as portable

ROOT = Path(__file__).resolve().parents[1]


class GitOpsBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.f = portable.DeliveryBoundaryTests('test_post_install_actual_reusable_argument_path')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root, self.metadata = self.f.root, self.f.metadata
        self.checkout, _ = self.f.gitops_checkout()
        self.workflow = yaml.load((ROOT / '.github/workflows/openshift-post-install.yaml').read_text(), Loader=yaml.BaseLoader)
        self.steps = self.workflow['jobs']['configure']['steps']
        self.validation = next(x['run'] for x in self.steps if x.get('name') == 'Validate Selected Cluster Contract')
        self.bootstrap = next(x['run'] for x in self.steps if x.get('name') == 'Bootstrap ArgoCD GitOps')
        self.calls, self.applied = self.root / 'oc-calls.jsonl', self.root / 'applied.jsonl'
        tools = self.root / 'tools'; tools.mkdir()
        oc = tools / 'oc'
        oc.write_text('#!' + sys.executable + '\n' + r'''
import json,os,pathlib,sys
args=sys.argv[1:]; root=pathlib.Path(os.environ['SYNTHETIC_ROOT'])
with (root/'oc-calls.jsonl').open('a') as out:out.write(json.dumps(args)+'\n')
state=root/'subscription-applied'
if args[:2]==['get','argocd']:sys.exit(0 if state.exists() else 1)
if args[:2]==['get','csv']:
 if state.exists():print(os.environ['GITOPS_OPERATOR_NAME']+'.synthetic Succeeded')
elif args[:2]==['get','subscription']:print('True')
elif args[:2]==['get','cm']:print('SYNTHETIC PUBLIC CA FIXTURE; NOT A REAL CERTIFICATE')
elif args[:2]==['get','application']:print('Synced' if 'sync.status' in ' '.join(args) else 'Healthy')
elif args[:2]==['create','configmap']:
 print(json.dumps({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'synthetic-tls'}}))
elif args and args[0]=='apply':
 source=args[args.index('-f')+1]; text=sys.stdin.read() if source=='-' else pathlib.Path(source).read_text()
 with (root/'applied.jsonl').open('a') as out:out.write(json.dumps({'args':args,'yaml':text})+'\n')
 if source.endswith('/subscription.yaml'):state.touch()
''')
        oc.chmod(0o755)
        sleep = tools / 'sleep'; sleep.write_text('#!/bin/sh\nexit 0\n'); sleep.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                    'CLUSTER': self.f.selected.name, 'CLUSTER_DIR': str(self.f.selected),
                    'ARTIFACT_MANIFEST': str(self.f.manifest), 'RAW_TARGET_ROOT': str(self.f.raw),
                    'GITOPS_TARGET_ROOT': str(self.checkout), 'GITOPS_BOOTSTRAP_DIR': str(self.root/'output'),
                    'GITHUB_ENV': str(self.root/'github-env'), 'GITHUB_STEP_SUMMARY': str(self.root/'summary'),
                    'SYNTHETIC_ROOT': str(self.root), 'ARGO_GIT_TOKEN': 'SYNTHETIC-NOT-A-CREDENTIAL'}

    def save(self):
        (self.f.selected/'metadata.yaml').write_text(yaml.safe_dump(self.metadata))
        (self.f.raw/'data/openshift'/self.f.selected.name/'metadata.yaml').write_bytes((self.f.selected/'metadata.yaml').read_bytes())
        manifest=yaml.safe_load(self.f.manifest.read_text())
        for target in manifest['targets']:
            for entry in target['files']:
                entry['sha256']=hashlib.sha256((self.f.raw/target['targetRoot']/entry['path']).read_bytes()).hexdigest()
        self.f.manifest.write_text(yaml.safe_dump(manifest))

    def preflight(self):
        self.save()
        return subprocess.run(['bash','-c',self.validation], cwd=ROOT, env=self.env, text=True, capture_output=True)

    def run_bootstrap(self):
        preflight=self.preflight();self.assertEqual(preflight.returncode,0,preflight.stderr)
        for line in Path(self.env['GITHUB_ENV']).read_text().splitlines():
            key,value=line.split('=',1);self.env[key]=value
        return subprocess.run(['bash','-c',self.bootstrap], cwd=ROOT, env=self.env, text=True, capture_output=True)

    def observed_calls(self):
        return [json.loads(x) for x in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def connected_without_site_registry(self):
        self.metadata['imageDelivery'].update(mode='connected',scopes=[],registry='')
        self.metadata['platformServices'].pop('registry',None)
        self.metadata['platformServices'].pop('registryTrustPolicy',None)
        self.metadata['platformServices']['gitops']['operatorSubscription'].update(
            source='selected-public-catalog',sourceNamespace='selected-marketplace',
            namespace='selected-operators',channel='true',installPlanApproval='Automatic')

    def test_connected_no_registry_uses_declared_subscription_and_recovery_selector(self):
        self.connected_without_site_registry()
        result=self.run_bootstrap();self.assertEqual(result.returncode,0,result.stderr)
        subscription=yaml.safe_load((self.root/'output/subscription.yaml').read_text())
        selected=self.metadata['platformServices']['gitops']['operatorSubscription']
        for key in ('source','sourceNamespace','channel','installPlanApproval'):
            self.assertEqual(subscription['spec'][key],selected[key])
        self.assertEqual(subscription['metadata']['namespace'],'selected-operators')
        calls=self.observed_calls()
        self.assertIn(['delete','pod','-n','selected-marketplace','-l','olm.catalogSource=selected-public-catalog'],calls)
        self.assertIn(['get','catalogsource','selected-public-catalog','-n','selected-marketplace'],calls)
        self.assertFalse(any(call[:2]==['get','cm'] or call[:2]==['create','configmap'] for call in calls))
        self.assertNotIn('redhat-operators-local',json.dumps(calls))
        self.assertIn('synced successfully',(self.root/'summary').read_text())

    def mirrored_receipt(self):
        self.metadata['imageDelivery'].update(mode='mirrored',scopes=['gitops-bootstrap'])
        self.metadata.setdefault('imagePolicyBundles',{})['gitopsBootstrap']='gitops-bootstrap'
        root=self.f.receipt('gitops-bootstrap')
        sources=self.f.validator.REQUIRED_SOURCES['gitops-bootstrap']
        document={'kind':'ImageDigestMirrorSet','spec':{'imageDigestMirrors':[{'source':s,'mirrors':['mirror.invalid/synthetic']} for s in sources]}}
        (root/'manifests/idms.yaml').write_text(yaml.safe_dump(document))
        bundle=yaml.safe_load((root/'bundle.yaml').read_text());bundle['spec']['requiredSources']=sources
        digest=hashlib.sha256()
        for path in sorted((root/'manifests').rglob('*')):
            if path.is_file():digest.update(path.relative_to(root/'manifests').as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
        bundle['metadata']['contentHash']=digest.hexdigest();(root/'bundle.yaml').write_text(yaml.safe_dump(bundle))

    def test_mirrored_selected_catalog_and_ca_are_consumed(self):
        self.mirrored_receipt()
        selected=self.metadata['platformServices']['gitops']['operatorSubscription']
        selected.update(source='selected-mirror-catalog',sourceNamespace='mirror-marketplace',
                        channel='mirrored-channel',installPlanApproval='Automatic',startingCSV='gitops.synthetic.v1')
        result=self.run_bootstrap();self.assertEqual(result.returncode,0,result.stderr)
        subscription=yaml.safe_load((self.root/'output/subscription.yaml').read_text())
        self.assertEqual(subscription['spec']['startingCSV'],'gitops.synthetic.v1')
        self.assertEqual(subscription['spec']['source'],'selected-mirror-catalog')
        calls=self.observed_calls()
        self.assertIn(['delete','pod','-n','mirror-marketplace','-l','olm.catalogSource=selected-mirror-catalog'],calls)
        self.assertTrue(any(call[:2]==['get','cm'] for call in calls))
        self.assertTrue(any(call[:2]==['create','configmap'] and any(x.startswith('--from-file=registry.example.com=') for x in call) for call in calls))

    def test_manual_approval_is_preserved_and_never_approved_automatically(self):
        self.connected_without_site_registry()
        self.metadata['platformServices']['gitops']['operatorSubscription']['installPlanApproval']='Manual'
        result=self.run_bootstrap();self.assertNotEqual(result.returncode,0)
        self.assertIn('Selected Manual InstallPlan approval',(self.root/'summary').read_text())
        subscription=yaml.safe_load((self.root/'output/subscription.yaml').read_text())
        self.assertEqual(subscription['spec']['installPlanApproval'],'Manual')
        self.assertFalse(any('installplan' in ' '.join(call).lower() and ('patch' in call or 'approve' in call) for call in self.observed_calls()))

    def test_runtime_outputs_cannot_mutate_raw_or_customer_checkout(self):
        for target in (self.f.raw/'new-output', self.checkout/'new-output'):
            with self.subTest(target=str(target)):
                self.env['GITOPS_BOOTSTRAP_DIR']=str(target)
                result=self.preflight();self.assertNotEqual(result.returncode,0)
                self.assertIn('runtime output must be separate',result.stderr)
                self.assertFalse(target.exists());self.assertFalse(self.calls.exists())

    def test_missing_and_conflicting_selection_stops_before_any_api(self):
        import copy
        baseline=copy.deepcopy(self.metadata)
        cases=[('channel',lambda m:m['platformServices']['gitops']['operatorSubscription'].pop('channel')),
               ('sourceNamespace',lambda m:m['platformServices']['gitops']['operatorSubscription'].pop('sourceNamespace')),
               ('installPlanApproval',lambda m:m['platformServices']['gitops']['operatorSubscription'].update(installPlanApproval='invented')),
               ('conflicts',lambda m:m['platformServices'].update(registry='conflicting.invalid:5443')),
               ('without a registry',lambda m:(m['imageDelivery'].update(registry=''),m['platformServices'].update(registry='')))]
        for expected,mutate in cases:
            with self.subTest(expected=expected):
                self.metadata=copy.deepcopy(baseline);mutate(self.metadata)
                result=self.preflight();self.assertNotEqual(result.returncode,0,result.stderr)
                self.assertIn(expected,result.stderr)
                self.assertFalse(self.calls.exists())
                self.assertFalse((self.root/'github-env').exists())

if __name__=='__main__':unittest.main()
