"""Offline update-chain regression tests; all mutations use temporary roots."""
import sys
sys.dont_write_bytecode = True
import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_manifest
import check_update
import local_update_guard as guard


def write(root, name, value):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value),encoding='utf8')


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='update-safety-')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.root=self.base/'live';self.root.mkdir()
        for name,value in {'VERSION':'1.0.0','SKILL.md':'local rules','updates.json':json.dumps({'update_source':None}),'scripts/local_update_guard.py':'guard','scripts/apply_update.py':'entry','references/local-delivery-quality.md':'quality','plain.txt':'original'}.items():write(self.root,name,value)
        with contextlib.redirect_stdout(io.StringIO()):build_manifest.build(self.root)

    def call_check(self,remote=None):
        out,err=io.StringIO(),io.StringIO()
        with patch.object(sys,'argv',['check_update','--skill-root',str(self.root)]), patch.object(check_update,'fetch_remote_updates',return_value=remote) as fetch, contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=check_update.main()
        return code,out.getvalue(),err.getvalue(),fetch.call_count

    def candidate(self,name='candidate',version='1.1.0'):
        target=self.base/name
        shutil.copytree(self.root,target,ignore=shutil.ignore_patterns('local-overrides'))
        write(target,'VERSION',version);write(target,'plain.txt','upstream '+version)
        with contextlib.redirect_stdout(io.StringIO()):build_manifest.build(target)
        return target

    def stage(self,candidate,name='stage'):
        stage=self.base/name
        with contextlib.redirect_stdout(io.StringIO()):guard.prepare(self.root,stage,candidate)
        write(stage,'review.json',{'status':'approved_no_conflict','conflicts':[],'reviewed_by':'isolated test'})
        return stage

    def apply(self,stage):
        with contextlib.redirect_stdout(io.StringIO()):guard.apply(self.root,stage)

    def test_version_normalization_and_invalid_values(self):
        self.assertEqual(check_update.parse_version('1.2'),(1,2,0))
        for value in ['1.2.3.4','-1.2.3','1..2','1.2-beta',None,1,'']:
            with self.subTest(value=value),self.assertRaises(ValueError):check_update.parse_version(value)

    def test_delta_replays_out_of_order_remove_readd(self):
        hist=[{'version':'1.3','added':['a']},{'version':'1.1','added':['b']},{'version':'1.2','removed':['a','b']},{'version':'1.4','modified':['a']}]
        self.assertEqual(check_update.collect_delta(hist,'1.0'),({'a'},set(),{'b'}))
        for invalid in [None,[{}],[{'version':'1.1','added':'a'}],[{'version':'1.1','added':['a'],'removed':['a']}],[{'version':'1.1'},{'version':'1.1.0'}]]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):check_update.collect_delta(invalid,'1.0')

    def test_unset_source_is_offline_and_invalid_local_metadata_exit4(self):
        self.assertEqual(self.call_check()[::3],(0,0))
        for value in ['[',[],{'update_source':42}]:
            write(self.root,'updates.json',value)
            code,out,err,calls=self.call_check()
            self.assertEqual(code,4);self.assertEqual(calls,0);self.assertNotIn('Traceback',err)
        write(self.root,'updates.json',{'update_source':None});write(self.root,'VERSION','1.2.3.4')
        self.assertEqual(self.call_check()[0],4)

    def test_invalid_remote_metadata_exit4_and_valid_updates(self):
        write(self.root,'updates.json',{'update_source':'https://unused.invalid'})
        for remote in [[],{'latest_version':'1.2.3.4'},{'latest_version':'2.0','history':[]},{'latest_version':'2.0','history':[{'version':'3.0'}]},{'latest_version':'2.0','history':False}]:
            code,out,err,calls=self.call_check(remote)
            self.assertEqual(code,4);self.assertNotIn('Traceback',err)
        self.assertEqual(self.call_check({'latest_version':'1.0','history':[]})[0],0)
        code,out,err,calls=self.call_check({'latest_version':'1.1','history':[{'version':'1.1','modified':['plain.txt']}]})
        self.assertEqual(code,0);self.assertIn('NEW ',out)
        with patch.object(check_update,'fetch_remote_updates',side_effect=OSError('offline')),patch.object(sys,'argv',['check','--skill-root',str(self.root)]),contextlib.redirect_stderr(io.StringIO()):self.assertEqual(check_update.main(),3)

    def test_preserves_current_future_and_deleted_rules_across_two_updates(self):
        candidate=self.candidate()
        write(self.root,'new-rule.md','future local rule')
        write(self.root,'plain.txt','locally changed')
        (self.root/'references/local-delivery-quality.md').unlink()
        stage=self.stage(candidate);self.apply(stage)
        self.assertEqual((self.root/'plain.txt').read_text(),'locally changed')
        self.assertFalse((self.root/'references/local-delivery-quality.md').exists())
        self.assertEqual((self.root/'new-rule.md').read_text(),'future local rule')
        candidate2=self.candidate('candidate2','1.2.0')
        write(candidate2,'new-rule.md','upstream conflicting rule')
        write(candidate2,'references/local-delivery-quality.md','upstream resurrected rule')
        stage2=self.stage(candidate2,'stage2');self.apply(stage2)
        self.assertEqual((self.root/'new-rule.md').read_text(),'future local rule')
        self.assertFalse((self.root/'references/local-delivery-quality.md').exists())
        registry=json.loads((self.root/'local-overrides/registry.json').read_text())
        self.assertIn('new-rule.md',registry['protected_paths'])
        self.assertIn('references/local-delivery-quality.md',registry['protected_paths'])
        self.assertEqual((self.root/'VERSION').read_text(),'1.2.0')

    def test_future_registry_paths_stay_protected(self):
        candidate=self.candidate();write(candidate,'future.md','upstream')
        write(self.root,'local-overrides/registry.json',{'protected_paths':['future.md']})
        stage=self.stage(candidate);self.apply(stage)
        self.assertFalse((self.root/'future.md').exists())

    def test_after_staging_changes_and_plan_reduction_fail_closed(self):
        candidate=self.candidate();stage=self.stage(candidate)
        plan=json.loads((stage/'plan.json').read_text());plan['protected_paths']=[];write(stage,'plan.json',plan)
        with self.assertRaisesRegex(ValueError,'Protected paths'):self.apply(stage)
        stage2=self.stage(candidate,'stage2')
        write(self.root,'local-overrides/registry.json',{'protected_paths':['new-future-rule.md']})
        with self.assertRaisesRegex(ValueError,'registry changed'):self.apply(stage2)
        stage3=self.stage(candidate,'stage3');write(self.root,'added-after-stage.md','new user rule')
        with self.assertRaisesRegex(ValueError,'Local files changed'):self.apply(stage3)

    def test_guard_failure_exit_nonzero_without_traceback(self):
        err=io.StringIO()
        with patch.object(sys,'argv',['guard','apply','--root',str(self.root),'--stage',str(self.base/'missing-stage')]),contextlib.redirect_stderr(err):self.assertEqual(guard.main(),4)
        self.assertNotIn('Traceback',err.getvalue())

    def test_invalid_candidate_version_never_reaches_apply(self):
        candidate=self.candidate();write(candidate,'VERSION','1.2.3.4')
        with self.assertRaisesRegex(ValueError,'Version must'):self.stage(candidate)
        self.assertEqual((self.root/'VERSION').read_text(),'1.0.0')

    def test_invalid_registry_refuses_prepare(self):
        candidate=self.candidate()
        for index,value in enumerate([[],{'protected_paths':'rule.md'},{'protected_paths':['../rule.md']}]):
            write(self.root,'local-overrides/registry.json',value)
            with self.assertRaises(ValueError):self.stage(candidate,'invalid-registry-'+str(index))

    def test_manifest_replace_failure_preserves_old_baseline(self):
        before=(self.root/'manifest.json').read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('replace failed')),self.assertRaises(OSError):
            build_manifest.build(self.root)
        self.assertEqual((self.root/'manifest.json').read_bytes(),before)
        self.assertEqual(list(self.root.glob('.manifest-*.tmp')),[])

    def test_apply_rollback_restores_files_and_version(self):
        candidate=self.candidate();write(candidate,'z-fail.txt','new')
        stage=self.stage(candidate);original=shutil.copy2
        def fail_once(src,dest,*a,**kw):
            if Path(dest)==self.root/'z-fail.txt':raise OSError('injected write failure')
            return original(src,dest,*a,**kw)
        with patch.object(guard.shutil,'copy2',side_effect=fail_once),self.assertRaisesRegex(OSError,'injected'):self.apply(stage)
        self.assertEqual((self.root/'plain.txt').read_text(),'original')
        self.assertEqual((self.root/'VERSION').read_text(),'1.0.0')
        self.assertEqual(json.loads((stage/'result.json').read_text())['status'],'failed_rolled_back')

    def test_manifest_refuses_customized_root_and_invalid_metadata(self):
        before=(self.root/'manifest.json').read_bytes()
        write(self.root,'local-overrides/local-rule.md','local')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(build_manifest.build(self.root),2)
        self.assertEqual((self.root/'manifest.json').read_bytes(),before)
        self.assertFalse(any('local-overrides' in p.parts for p in build_manifest.iter_files(self.root)))
        other=self.base/'author';other.mkdir();write(other,'VERSION','1.0');write(other,'manifest.json',{'files':[]})
        err=io.StringIO()
        with patch.object(sys,'argv',['build','--skill-root',str(other)]),contextlib.redirect_stderr(err):self.assertEqual(build_manifest.main(),4)
        self.assertNotIn('Traceback',err.getvalue())
        self.assertEqual(json.loads((other/'manifest.json').read_text()),{'files':[]})

    def test_safe_paths(self):
        for rel in ['../escape','/absolute','local-overrides/rules','LOCAL-OVERRIDES/rules','a/../b','a\\b','C:/bad','']:
            with self.subTest(rel=rel),self.assertRaises(ValueError):guard.safe(self.root,rel)
        self.assertEqual(guard.safe(self.root,'references/rule.md'),self.root/'references/rule.md')


if __name__=='__main__':unittest.main(verbosity=2)
