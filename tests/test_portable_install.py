"""Offline joins for the existing declared-hardware and CLife staging helpers."""
from pathlib import Path
import contextlib, importlib.util, io, shutil, tempfile, unittest, tarfile, hashlib
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
def module(name):
 spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts'/name)
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def fixture_archive(selected, bundle):
 archive=bundle.parent/(bundle.name+'.tar.gz')
 with tarfile.open(archive,'w:gz') as tar:
  for path in sorted(bundle.iterdir()):tar.add(path,arcname='official/'+path.name)
 path=selected/'metadata.yaml';metadata=yaml.safe_load(path.read_text())
 metadata['ciliumDay1']['manifestArchive']['sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
 path.write_text(yaml.safe_dump(metadata,sort_keys=False));return archive

class PortableInstallTests(unittest.TestCase):
 def setUp(self):
  self.hardware=module('resolve-agent-hardware.py');self.clife=module('enrich-cilium-day1-manifests.py')
  self.example=ROOT/'data/openshift/example-third-party'
 def test_declared_inventory_validates_without_vendor_discovery(self):
  data=[yaml.safe_load((self.example/f).read_text()) for f in ['metadata.yaml','install-config.yaml','agent-config.yaml']]
  with patch.object(self.hardware,'run_isctl',side_effect=AssertionError('vendor discovery forbidden in declared path')):
   hosts=self.hardware.validate_identity_inputs(*data,declared=True)
   self.assertEqual(len(hosts),3)
   self.assertEqual(data[2]['rendezvousIP'],'192.0.2.11')
 def test_missing_or_invalid_declared_mac_fails(self):
  data=[yaml.safe_load((self.example/f).read_text()) for f in ['metadata.yaml','install-config.yaml','agent-config.yaml']]
  data[2]['hosts'][0]['interfaces'][0]['macAddress']='invalid'
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
   self.hardware.validate_identity_inputs(*data,declared=True)
 def test_verified_bundle_join_retains_canonical_cilium_and_derives_api(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory); selected=root/'example-third-party';shutil.copytree(self.example,selected);bundle=root/'bundle';bundle.mkdir()
   metadata=yaml.safe_load((selected/'metadata.yaml').read_text());image=metadata['ciliumDay1']['images']['clife']
   deployment={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'clife-controller-manager'},'spec':{'template':{'spec':{'containers':[{'name':'manager','image':image}]}}}}
   subscription={'apiVersion':'operators.coreos.com/v1alpha1','kind':'Subscription','metadata':{'name':'clife'},'spec':{}}
   (bundle/'deployment.yaml').write_text(yaml.safe_dump(deployment));(bundle/'subscription.yaml').write_text(yaml.safe_dump(subscription))
   original=(selected/'manifests/ciliumconfig.yaml').read_bytes()
   self.assertEqual(self.clife.render_manifests(ROOT,selected,bundle_dir=bundle,bundle_archive=fixture_archive(selected,bundle)),2)
   self.assertEqual((selected/'manifests/ciliumconfig.yaml').read_bytes(),original)
   rendered=yaml.safe_load((selected/'manifests/apps_v1_deployment_clife-controller-manager.yaml').read_text())
   env=rendered['spec']['template']['spec']['containers'][0]['env']
   self.assertEqual({x['name']:x['value'] for x in env},{'KUBERNETES_SERVICE_HOST':'api-int.example-third-party.example.com','KUBERNETES_SERVICE_PORT':'6443'})
   validator=module('validate-selected-cluster-contract.py');errors=[]
   validator.validate_common(selected,errors);validator.validate_cilium(selected,metadata,errors)
   self.assertEqual(errors,[])
   # Mismatched exact-version artifact must fail, not silently repair the release.
   deployment['spec']['template']['spec']['containers'][0]['image']='containers.isovalent.com/clife:wrong-version'
   (bundle/'deployment.yaml').write_text(yaml.safe_dump(deployment))
   with self.assertRaisesRegex(ValueError,'does not match'):self.clife.render_manifests(ROOT,selected,bundle_dir=bundle,bundle_archive=fixture_archive(selected,bundle))

class DeliveryBoundaryTests(unittest.TestCase):
 """Synthetic receipts test validation only; they are never operational mirror evidence."""
 def setUp(self):
  import hashlib
  self.hashlib=hashlib;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.selected=self.root/'example-third-party'
  shutil.copytree(ROOT/'data/openshift/example-third-party',self.selected)
  self.validator=module('validate-selected-cluster-contract.py');self.enricher=module('enrich-cilium-day1-manifests.py')
  self.metadata=yaml.safe_load((self.selected/'metadata.yaml').read_text())
  self.raw=self.root/'raw';rawdata=self.raw/'data/openshift/example-third-party';shutil.copytree(self.selected,rawdata)
  files=[{'path':p.relative_to(self.raw/'data').as_posix(),'sha256':self.hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(rawdata.rglob('*')) if p.is_file()]
  self.manifest=self.root/'manifest.yaml';self.manifest.write_text(yaml.safe_dump({'targets':[{'repo':'synthetic-compute','targetRoot':'data','files':files}]}))
  bundle=self.root/'official-fixture';bundle.mkdir()
  deployment={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'clife-controller-manager'},'spec':{'template':{'spec':{'containers':[{'name':'manager','image':self.metadata['ciliumDay1']['images']['clife']}]}}}}
  subscription={'kind':'Subscription','metadata':{'name':'clife'},'spec':{'channel':self.metadata['ciliumDay1']['channel']}}
  (bundle/'fixture.yaml').write_text(yaml.safe_dump_all([deployment,subscription]))
  self.archive=fixture_archive(self.selected,bundle)
  self.metadata=yaml.safe_load((self.selected/'metadata.yaml').read_text())
  shutil.copy2(self.selected/'metadata.yaml',rawdata/'metadata.yaml')
  files=[{'path':p.relative_to(self.raw/'data').as_posix(),'sha256':self.hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(rawdata.rglob('*')) if p.is_file()]
  self.manifest.write_text(yaml.safe_dump({'targets':[{'repo':'synthetic-compute','targetRoot':'data','files':files}]}))
  self.enricher.render_manifests(ROOT,self.selected,bundle_dir=bundle,bundle_archive=self.archive)
  (self.selected/'openshift').mkdir()
  for p in (self.selected/'manifests').iterdir():shutil.copy2(p,self.selected/'openshift'/p.name)
 def validate(self):
  return self.validator.validate_action(self.selected,'deploy',artifact_manifest=self.manifest,raw_target_root=self.raw,agent_staging=True)
 def test_connected_hash_and_agent_staging_without_mirror_receipts(self):
  self.assertEqual(self.validate(),[])
  self.assertTrue(any('artifact-manifest' in e for e in self.validator.validate_action(self.selected,'deploy')))
 def test_corrupt_raw_and_corrupt_agent_staging_fail(self):
  path=self.raw/'data/openshift/example-third-party/agent-config.yaml';path.write_text(path.read_text()+'\n# changed\n')
  self.assertTrue(any('hash mismatch' in e for e in self.validate()))
  path=self.selected/'openshift/subscription.yaml';path.write_text(path.read_text()+'\n# changed\n')
  self.assertTrue(any('differs from enriched' in e for e in self.validate()))
 def test_private_enrichment_allowed_but_nonsecret_install_drift_rejected(self):
  path=self.selected/'install-config.yaml';data=yaml.safe_load(path.read_text())
  data['pullSecret']='synthetic-private-fixture';data['sshKey']='ssh-ed25519 synthetic';data['additionalTrustBundle']='synthetic-ca-fixture'
  path.write_text(yaml.safe_dump(data));self.assertEqual(self.validate(),[])
  data['baseDomain']='wrong.example.invalid';path.write_text(yaml.safe_dump(data))
  self.assertTrue(any('non-secret intent differs' in e for e in self.validate()))
 def test_stale_extra_agent_yaml_fails(self):
  (self.selected/'openshift/old.yaml').write_text('kind: ConfigMap\n')
  self.assertTrue(any('YAML set differs' in e for e in self.validate()))
 def receipt(self,scope):
  root=self.selected/'image-policy-bundles'/scope;(root/'manifests').mkdir(parents=True)
  images=list(self.metadata['ciliumDay1']['images'].values()) if scope=='cilium-day1' else ['platform:stable-4.19:4.19.21:4.19.21']
  sources=['containers.isovalent.com'] if scope=='cilium-day1' else ['quay.io/openshift-release-dev/ocp-release']
  idms={'kind':'ImageDigestMirrorSet','metadata':{'name':scope},'spec':{'imageDigestMirrors':[{'source':source,'mirrors':['mirror.invalid/synthetic']} for source in sources]}}
  (root/'manifests/idms.yaml').write_text(yaml.safe_dump(idms))
  digest=self.hashlib.sha256()
  for p in sorted((root/'manifests').rglob('*')):
   if p.is_file():digest.update(p.relative_to(root/'manifests').as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
  data={'metadata':{'scope':scope,'name':scope,'specHash':'0'*64,'contentHash':digest.hexdigest(),'version':'synthetic-only'},'spec':{'registry':self.metadata['imageDelivery']['registry'],'workflow':'synthetic','workflowRun':'synthetic','requiredSources':sources,'requiredImages':images,'manifests':['manifests/idms.yaml']}}
  (root/'bundle.yaml').write_text(yaml.safe_dump(data))
  for source in (root/'manifests').glob('*.yaml'):
   for dest in ['manifests','openshift']:shutil.copy2(source,self.selected/dest/f'{scope}--{source.name}')
  return root
 def mirrored(self):
  self.metadata['imageDelivery'].update(mode='mirrored',scopes=['ocp-install-core','cilium-day1'])
  (self.selected/'metadata.yaml').write_text(yaml.safe_dump(self.metadata))
 def test_mirrored_day1_only_does_not_require_day2(self):
  self.mirrored();self.receipt('ocp-install-core');self.receipt('cilium-day1')
  self.assertEqual(self.validate(),[])
 def test_valid_receipt_without_agent_policy_staging_fails(self):
  self.mirrored();self.receipt('ocp-install-core');self.receipt('cilium-day1')
  (self.selected/'manifests/cilium-day1--idms.yaml').unlink()
  self.assertTrue(any('lack exact selected mirror policy' in e for e in self.validate()))
 def test_mirrored_missing_wrong_release_or_corrupt_receipts_fail(self):
  self.mirrored();self.assertTrue(any('bundle metadata' in e for e in self.validate()))
  core=self.receipt('ocp-install-core');cilium=self.receipt('cilium-day1')
  data=yaml.safe_load((core/'bundle.yaml').read_text());data['spec']['requiredImages']=['platform:stable-4.20:4.20.0:4.20.0'];(core/'bundle.yaml').write_text(yaml.safe_dump(data))
  self.assertTrue(any('exact OpenShift' in e for e in self.validate()))
  (cilium/'manifests/idms.yaml').write_text('kind: ConfigMap\n')
  self.assertTrue(any('contentHash mismatch' in e for e in self.validate()))
 def test_cli_archive_hash_and_consumed_directory_are_bound(self):
  import subprocess,sys
  bundle=self.root/'official-fixture'
  args=[sys.executable,str(ROOT/'scripts/enrich-cilium-day1-manifests.py'),'--cluster-dir',str(self.selected),'--bundle-dir',str(bundle),'--bundle-archive',str(self.archive)]
  good=subprocess.run(args,text=True,capture_output=True);self.assertEqual(good.returncode,0,good.stderr)
  path=bundle/'fixture.yaml';path.write_text(path.read_text()+'\n# altered after archive verification\n')
  bad=subprocess.run(args,text=True,capture_output=True)
  self.assertNotEqual(bad.returncode,0);self.assertIn('directory YAML bytes/set differ',bad.stderr)
  self.archive.write_bytes(self.archive.read_bytes()+b'changed')
  bad=subprocess.run(args,text=True,capture_output=True)
  self.assertNotEqual(bad.returncode,0);self.assertIn('SHA-256 conflicts',bad.stderr)
 def test_delivery_metadata_is_required_without_fallback(self):
  self.metadata.pop('imageDelivery');(self.selected/'metadata.yaml').write_text(yaml.safe_dump(self.metadata))
  self.assertTrue(any('requires explicit imageDelivery' in e for e in self.validate()))
 def test_conflicting_manager_digest_fails(self):
  bundle=self.root/'wrong';bundle.mkdir();image=self.metadata['ciliumDay1']['images']['clife'].split('@')[0]+'@sha256:'+'f'*64
  deployment={'kind':'Deployment','metadata':{'name':'clife-controller-manager'},'spec':{'template':{'spec':{'containers':[{'name':'manager','image':image}]}}}}
  (bundle/'wrong.yaml').write_text(yaml.safe_dump(deployment))
  with self.assertRaisesRegex(ValueError,'digest conflicts'):self.enricher.render_manifests(ROOT,self.selected,bundle_dir=bundle,bundle_archive=fixture_archive(self.selected,bundle))

 def gitops_checkout(self):
  import subprocess
  checkout=self.root/'customer-gitops';checkout.mkdir()
  def git(*args):return subprocess.check_output(['git','-C',str(checkout),*args],stderr=subprocess.DEVNULL,text=True).strip()
  git('init','-b','secure-ai');git('config','user.name','Synthetic fixture');git('config','user.email','fixture@example.invalid')
  cluster=checkout/'clusters/example-third-party';cluster.mkdir(parents=True)
  (cluster/'kustomization.yaml').write_text('apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [namespace.yaml]\n')
  (cluster/'namespace.yaml').write_text('apiVersion: v1\nkind: Namespace\nmetadata: {name: synthetic-only}\n')
  git('add','.');git('commit','-m','Synthetic workflow test, not a customer deployment')
  git('remote','add','origin',self.metadata['platformServices']['gitops']['repoURL'])
  return checkout,git
 def test_post_install_actual_reusable_argument_path(self):
  import subprocess,os,re
  checkout,git=self.gitops_checkout()
  pipeline=yaml.load((ROOT/'.github/workflows/openshift-pipeline.yaml').read_text(),Loader=yaml.BaseLoader)
  workflow=yaml.load((ROOT/'.github/workflows/openshift-post-install.yaml').read_text(),Loader=yaml.BaseLoader)
  contract={'cluster_dir':str(self.selected),'artifact_manifest':str(self.manifest),'raw_target_root':str(self.raw),'gitops_target_root':str(checkout)}
  caller=pipeline['jobs']['post_install'];self.assertEqual(caller['uses'],'./.github/workflows/openshift-post-install.yaml')
  resolved={'cluster_name':self.selected.name}
  for key,value in contract.items():
   self.assertEqual(caller['with'][key],"${{ fromJSON(inputs.post_install_contract)."+key+" || '' }}")
   for trigger in ('workflow_dispatch','workflow_call'):
    self.assertEqual(workflow['on'][trigger]['inputs'][key]['type'],'string')
   resolved[key]=value
  env=os.environ.copy()
  for key,value in workflow['jobs']['configure']['env'].items():
   match=re.fullmatch(r"\$\{\{ inputs\.([a-z_]+) \}\}",value);self.assertIsNotNone(match)
   env[key]=resolved[match.group(1)]
  env['GITHUB_STEP_SUMMARY']=str(self.root/'summary')
  env['GITHUB_ENV']=str(self.root/'github-env')
  env['GITOPS_BOOTSTRAP_DIR']=str(self.root/'bootstrap')
  steps=workflow['jobs']['configure']['steps'];validation=next(x for x in steps if x.get('name')=='Validate Selected Cluster Contract')
  self.assertLess(steps.index(validation),next(i for i,x in enumerate(steps) if x.get('name')=='Retrieve Kubeconfig'))
  self.assertFalse(any(x.get('name')=='Enrich Cilium Day 1 Manifests' for x in steps))
  def run():return subprocess.run(['bash','-c',validation['run']],cwd=ROOT,env=env,text=True,capture_output=True)
  before={p:p.read_bytes() for p in self.raw.rglob('*') if p.is_file()}
  good=run();self.assertEqual(good.returncode,0,good.stderr)
  self.assertEqual(before,{p:p.read_bytes() for p in self.raw.rglob('*') if p.is_file()})
  env['ARTIFACT_MANIFEST']=''
  partial=run();self.assertNotEqual(partial.returncode,0);self.assertIn('must both be absolute',partial.stdout)
  env['ARTIFACT_MANIFEST']='';env['RAW_TARGET_ROOT']=''
  missing=run();self.assertNotEqual(missing.returncode,0);self.assertIn('artifact-manifest',missing.stderr)
  env.update(ARTIFACT_MANIFEST=str(self.manifest),RAW_TARGET_ROOT=str(self.raw))
  git('remote','set-url','origin','https://github.com/example/conflicting-repo.git')
  conflict=run();self.assertNotEqual(conflict.returncode,0);self.assertIn('origin conflicts',conflict.stderr)
  git('remote','set-url','origin',self.metadata['platformServices']['gitops']['repoURL'])
  (checkout/'clusters/example-third-party/kustomization.yaml').unlink()
  missingroot=run();self.assertNotEqual(missingroot.returncode,0);self.assertIn('requires exactly one Kustomization',missingroot.stderr)
 def test_post_install_mirrored_receipt_and_customer_root(self):
  checkout,git=self.gitops_checkout()
  self.metadata['imageDelivery'].update(mode='mirrored',scopes=['gitops-bootstrap'])
  self.metadata.setdefault('imagePolicyBundles',{})['gitopsBootstrap']='gitops-bootstrap'
  (self.selected/'metadata.yaml').write_text(yaml.safe_dump(self.metadata))
  missing=self.validator.validate_action(self.selected,'post-install',gitops_target_root=checkout)
  self.assertTrue(any('bundle metadata' in e for e in missing))
  root=self.receipt('gitops-bootstrap')
  sources=self.validator.REQUIRED_SOURCES['gitops-bootstrap']
  idms={'kind':'ImageDigestMirrorSet','metadata':{'name':'synthetic-bootstrap'},'spec':{'imageDigestMirrors':[{'source':source,'mirrors':['mirror.invalid/synthetic']} for source in sources]}}
  (root/'manifests/idms.yaml').write_text(yaml.safe_dump(idms))
  bundle=yaml.safe_load((root/'bundle.yaml').read_text());bundle['spec']['requiredSources']=sources
  digest=self.hashlib.sha256()
  for path in sorted((root/'manifests').rglob('*')):
   if path.is_file():digest.update(path.relative_to(root/'manifests').as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
  bundle['metadata']['contentHash']=digest.hexdigest();(root/'bundle.yaml').write_text(yaml.safe_dump(bundle))
  self.assertEqual(self.validator.validate_action(self.selected,'post-install',gitops_target_root=checkout),[])
 def test_post_install_rejects_missing_gitops_and_raw_staging_alias(self):
  errors=self.validator.validate_action(self.selected,'post-install',artifact_manifest=self.manifest,raw_target_root=self.raw)
  self.assertTrue(any('gitops-target-root' in e for e in errors))
  # Explicit alias with the same selected directory must fail before checking hashes.
  alias=self.root/'alias';(alias/'data/openshift').mkdir(parents=True)
  (alias/'data/openshift'/self.selected.name).symlink_to(self.selected,target_is_directory=True)
  errors=[];self.validator.validate_raw_artifacts(self.selected,self.manifest,alias,errors)
  self.assertTrue(any('separate trees' in e for e in errors))
 def test_gitops_revision_root_and_cleanliness_conflicts_fail(self):
  checkout,git=self.gitops_checkout()
  errors=[];self.validator.validate_gitops_root(self.metadata,checkout,errors);self.assertEqual(errors,[])
  (checkout/'unreviewed.yaml').write_text('kind: Secret\n')
  errors=[];self.validator.validate_gitops_root(self.metadata,checkout,errors);self.assertTrue(any('uncommitted' in e for e in errors))
  (checkout/'unreviewed.yaml').unlink()
  self.metadata['platformServices']['gitops']['targetRevision']='missing-reviewed-ref'
  errors=[];self.validator.validate_gitops_root(self.metadata,checkout,errors);self.assertTrue(any('cannot verify' in e for e in errors))
  self.metadata['gitopsBootstrapPath']='../outside'
  errors=[];self.validator.validate_gitops_root(self.metadata,checkout,errors);self.assertTrue(any('unsafe' in e for e in errors))

if __name__ == "__main__": unittest.main()
