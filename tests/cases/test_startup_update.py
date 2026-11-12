"""Startup advice is optional; update application remains explicitly authorized."""
from pathlib import Path
import contextlib,io,json,sys,tempfile,time,threading,unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import startup_update as startup
import skill_state

class StartupUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'skill';self.root.mkdir()
        (self.root/'MYPPT_VERSION').write_text('2.0');(self.root/'VERSION').write_text('1.0.20')
        (self.root/'updates.json').write_text(json.dumps({'update_source':'fixture-upstream'}))
        self.config={'schema':'myppt-startup-update/v1','release_metadata_url':'https://fixture/release',
                     'upstream_metadata_url':'https://fixture/upstream','upstream_source':'fixture-upstream'}
        self.write_config()
        self.remote={'https://fixture/release':{'tag_name':'v2.0'},
                     'https://fixture/upstream':{'latest_version':'1.0.20','history':[]}}
    def write_config(self):
        (self.root/'startup-update.json').write_text(json.dumps(self.config),encoding='utf8')
    def run_check(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        def request(url,timeout):
            value=self.remote[url]
            if isinstance(value,Exception):raise value
            return value
        with patch.object(startup,'fetch',side_effect=request):result=startup.check_startup(self.root)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(result['workflow_action'],'continue_local')
        self.assertFalse(result['apply_authorized'])
        return result
    def upstream_new(self):
        self.remote['https://fixture/upstream']={'latest_version':'1.0.21','history':[{'version':'1.0.21'}]}
    def test_equal_versions_do_not_prompt(self):
        r=self.run_check();self.assertEqual(r['check_status'],'no_update');self.assertFalse(r['should_prompt'])
    def test_older_remote_does_not_downgrade(self):
        self.remote['https://fixture/release']={'tag_name':'v1.2'};r=self.run_check();self.assertFalse(r['should_prompt'])
    def test_myppt_release_update_prompts_with_own_version(self):
        self.remote['https://fixture/release']={'tag_name':'v2.1'};r=self.run_check()
        self.assertTrue(r['should_prompt']);self.assertEqual(r['updates'][0]['source'],'mypptskill')
        self.assertEqual(r['updates'][0]['local_version'],'2.0')
    def test_upstream_update_uses_separate_baseline(self):
        self.upstream_new();r=self.run_check();self.assertEqual(r['updates'][0]['local_version'],'1.0.20')
    def test_both_updates_are_batched_for_one_prompt(self):
        self.remote['https://fixture/release']={'tag_name':'v2.1'};self.upstream_new();r=self.run_check()
        self.assertEqual(len(r['updates']),2);self.assertTrue(r['should_prompt'])
    def test_one_network_failure_preserves_other_update(self):
        self.remote['https://fixture/release']=OSError('offline');self.upstream_new();r=self.run_check()
        self.assertTrue(r['should_prompt']);self.assertEqual(r['checks'][0]['error_code'],3)
    def test_offline_is_unavailable_and_never_latest(self):
        for k in self.remote:self.remote[k]=OSError('offline')
        r=self.run_check();self.assertEqual(r['check_status'],'check_unavailable');self.assertFalse(r['should_prompt'])
        self.assertTrue(all(x['error_code']==3 for x in r['checks']))
    def test_malformed_remote_is_nonblocking(self):
        self.remote['https://fixture/release']={'tag_name':'broken'};r=self.run_check()
        self.assertFalse(r['should_prompt']);self.assertEqual(r['checks'][0]['error_code'],4)
    def test_upstream_inconsistent_history_is_nonblocking(self):
        self.remote['https://fixture/upstream']={'latest_version':'1.0.21','history':[]}
        r=self.run_check();self.assertFalse(r['should_prompt']);self.assertEqual(r['checks'][1]['error_code'],4)
    def test_prerelease_does_not_prompt(self):
        self.remote['https://fixture/release']={'tag_name':'v2.1','prerelease':True}
        self.assertFalse(self.run_check()['should_prompt'])
    def test_draft_does_not_prompt(self):
        self.remote['https://fixture/release']={'tag_name':'v2.1','draft':True}
        self.assertFalse(self.run_check()['should_prompt'])
    def test_missing_version_does_not_block_other_source(self):
        (self.root/'MYPPT_VERSION').unlink();self.upstream_new();r=self.run_check()
        self.assertTrue(r['should_prompt']);self.assertEqual(r['updates'][0]['source'],'upstream')
    def test_malformed_local_config_continues(self):
        (self.root/'startup-update.json').write_text('{');r=startup.check_startup(self.root)
        self.assertEqual(r['workflow_action'],'continue_local');self.assertEqual(r['check_status'],'check_unavailable')
    def test_upstream_source_mismatch_does_not_query_wrong_source(self):
        self.config['upstream_source']='another-source';self.write_config();self.upstream_new()
        with patch.object(startup,'fetch',return_value={'tag_name':'v2.0'}) as fetch:r=startup.check_startup(self.root)
        self.assertEqual(fetch.call_count,1);self.assertFalse(r['should_prompt'])
    def test_unset_metadata_url_continues(self):
        self.config['release_metadata_url']=None;self.write_config();self.assertFalse(self.run_check()['should_prompt'])
    def test_invalid_time_budgets_return_nonblocking_advice(self):
        for value in (0,-1,6,float('nan'),float('inf')):
            r=startup.check_startup(self.root,value);self.assertEqual(r['workflow_action'],'continue_local');self.assertFalse(r['should_prompt'])
    def test_no_reply_or_skip_does_not_authorize_update(self):
        r={'should_prompt':True,'updates':[{'source':'mypptskill'}]}
        for choice in (None,'skip','later','yes'):self.assertEqual(startup.decision_action(r,choice),'continue_local')
        self.assertEqual(startup.decision_action(r,'update'),'prepare_guarded_update')
    def test_update_choice_without_verified_update_keeps_local(self):
        self.assertEqual(startup.decision_action({'should_prompt':False,'updates':[]},'update'),'continue_local')
    def test_cli_unexpected_check_exception_continues_and_records_error(self):
        out=io.StringIO()
        with patch.object(startup,'check_startup',side_effect=RuntimeError('fixture')),contextlib.redirect_stdout(out):
            code=startup.main(['--skill-root',str(self.root)])
        r=json.loads(out.getvalue());self.assertEqual(code,0);self.assertEqual(r['checks'][0]['error_code'],4)
    def test_user_interrupt_remains_cancellation(self):
        with patch.object(startup,'check_startup',side_effect=KeyboardInterrupt),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(startup.main(['--skill-root',str(self.root)]),130)
    def test_report_cannot_overwrite_skill_configuration(self):
        p=self.root/'VERSION';before=p.read_bytes();r=self.run_check();startup.save_optional_report(p,self.root,r)
        self.assertEqual(p.read_bytes(),before);self.assertIn('report_error',r)
    def test_existing_report_is_preserved_without_blocking(self):
        p=self.base/'report.json';p.write_text('keep');r=self.run_check();startup.save_optional_report(p,self.root,r)
        self.assertEqual(p.read_text(),'keep');self.assertEqual(r['report_error']['workflow_action'],'continue_local')
    def test_unwritable_report_does_not_block(self):
        r=self.run_check()
        with patch.object(Path,'open',side_effect=PermissionError('denied')):startup.save_optional_report(self.base/'r.json',self.root,r)
        self.assertIn('report_error',r);self.assertEqual(r['workflow_action'],'continue_local')
    def test_own_release_version_is_frozen_with_rules(self):
        first=skill_state.inventory(self.root);(self.root/'MYPPT_VERSION').write_text('2.1')
        self.assertNotEqual(first['MYPPT_VERSION'],skill_state.inventory(self.root)['MYPPT_VERSION'])
    def test_startup_resources_are_protected_during_upstream_updates(self):
        registry=json.loads((startup.ROOT/'local-overrides/registry.json').read_text(encoding='utf-8-sig'))
        self.assertTrue({'MYPPT_VERSION','startup-update.json','scripts/startup_update.py','references/startup-update.md'}.issubset(set(registry['protected_paths'])))

class StartupTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'MYPPT_VERSION').write_text('2.0');(self.root/'VERSION').write_text('1.0.20')
        (self.root/'updates.json').write_text(json.dumps({'update_source':'fixture'}))
        self.stop=threading.Event();stop=self.stop
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                if self.path=='/rate-limit':
                    self.send_response(429);self.end_headers();return
                self.send_response(200)
                if self.path=='/oversize':self.send_header('Content-Length',str(2*1024*1024))
                if self.path=='/truncated':self.send_header('Content-Length','200')
                self.end_headers()
                try:
                    if self.path=='/slow':
                        while not stop.is_set():self.wfile.write(b' ');self.wfile.flush();stop.wait(.02)
                    else:self.wfile.write(b'{' if self.path=='/invalid' else b'{"tag_name":"v2.1"}')
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):
        self.stop.set();self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def check(self,mode,timeout=2):
        (self.root/'startup-update.json').write_text(json.dumps({'schema':'myppt-startup-update/v1','release_metadata_url':self.url+'/'+mode,'upstream_metadata_url':None,'upstream_source':'fixture'}))
        return startup.check_startup(self.root,timeout)
    def test_live_loopback_update(self):self.assertTrue(self.check('valid')['should_prompt'])
    def test_live_invalid_json_continues(self):self.assertEqual(self.check('invalid')['workflow_action'],'continue_local')
    def test_live_truncated_response_continues(self):
        r=self.check('truncated');self.assertFalse(r['should_prompt']);self.assertEqual(r['checks'][0]['error_code'],3)
    def test_live_size_limit_continues(self):self.assertFalse(self.check('oversize')['should_prompt'])
    def test_rate_limit_continues_without_prompt(self):
        r=self.check('rate-limit');self.assertFalse(r['should_prompt']);self.assertEqual(r['checks'][0]['error_code'],3)
    def test_slow_stream_has_parent_wall_clock_limit(self):
        t=time.monotonic();r=self.check('slow',.35);self.assertLess(time.monotonic()-t,3)
        self.assertFalse(r['should_prompt']);self.assertEqual(r['workflow_action'],'continue_local')
    def test_hung_dns_worker_has_parent_wall_clock_limit(self):
        with patch.object(startup,'WORKER','import time; time.sleep(60)'):
            t=time.monotonic();r=self.check('valid',.35)
        self.assertLess(time.monotonic()-t,3);self.assertEqual(r['check_status'],'check_unavailable')

if __name__=='__main__':unittest.main()
