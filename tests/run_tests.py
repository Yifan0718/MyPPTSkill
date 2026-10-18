"""Run the current development tests against an isolated copy of a Skill."""
from pathlib import Path
import argparse,sys,json,shutil,tempfile,subprocess,os
sys.dont_write_bytecode=True
WORKER=r'''
from pathlib import Path
import sys,unittest,json,io,contextlib,collections
sys.dont_write_bytecode=True
runtime=Path(sys.argv[1]);report=Path(sys.argv[2]);sys.path.insert(0,str(runtime))
suite=unittest.defaultTestLoader.discover(str(runtime),pattern='test_*.py')
def leaves(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):yield from leaves(t)
  else:yield t
groups=collections.Counter(t.__class__.__module__ for t in leaves(suite))
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
 result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=1).run(suite)
passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)-len(result.expectedFailures)
ok=result.wasSuccessful() and not result.skipped and not result.expectedFailures
data={'status':'passed' if ok else 'failed','run':result.testsRun,'passed':passed,'skipped':len(result.skipped),'expected_failures':len(result.expectedFailures),'groups':dict(sorted(groups.items())),'failures':[{'test':str(t),'detail':d} for t,d in result.failures+result.errors]}
report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
raise SystemExit(0 if ok else 1)
'''
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--skill-root',type=Path,default=Path(__file__).resolve().parent.parent/'skill/my-ppt-skill')
 ap.add_argument('--output',type=Path,default=Path(__file__).resolve().parent.parent/'test-results')
 ap.add_argument('--python-only',action='store_true',help='Run only Python; report partial coverage explicitly')
 ap.add_argument('--visual-fixture',type=Path,help='Also generate a two-slide editable fixture; it still needs real rendering and visual review')
 args=ap.parse_args();root=args.skill_root.resolve();output=args.output.resolve();cases=Path(__file__).resolve().parent/'cases'
 if not (root/'SKILL.md').is_file() or not (root/'scripts/verify_coverage_review.py').is_file():
  print('Skill directory is missing or incomplete. Extract the installation package and pass --skill-root <my-ppt-skill>.',file=sys.stderr);return 2
 if output.is_relative_to(root):
  print('Choose --output outside the installed Skill directory.',file=sys.stderr);return 2
 if args.visual_fixture and args.visual_fixture.resolve().is_relative_to(root):
  print('Choose --visual-fixture outside the installed Skill directory.',file=sys.stderr);return 2
 output.mkdir(parents=True,exist_ok=True)
 report=output/'test-summary.json'
 if report.exists():
  print('The output already contains a test report. Use a fresh --output directory to preserve earlier results.',file=sys.stderr);return 2
 state={'status':'running','scope':'python_only' if args.python_only else 'python_and_powershell','python':None,'entrypoints':None,'powershell':[],'visual_fixture':None}
 report.write_text(json.dumps(state),encoding='utf8')
 try:
  with tempfile.TemporaryDirectory(prefix='mypptskill-tests-') as temporary:
   runtime=Path(temporary)/'skill';runtime.mkdir()
   for p in root.rglob('*'):
    if not p.is_file():continue
    rel=p.relative_to(root)
    if any(part in ('.git','__pycache__') for part in rel.parts):continue
    if rel.parts[0]=='local-overrides' and rel.as_posix()!='local-overrides/registry.json':continue
    target=runtime/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
   for p in cases.iterdir():
    if p.is_file():shutil.copy2(p,runtime/'scripts'/p.name)
   worker=Path(temporary)/'worker.py';worker.write_text(WORKER,encoding='utf8')
   pyreport=Path(temporary)/'python.json'
   run=subprocess.run([sys.executable,'-B','-X','utf8',str(worker),str(runtime/'scripts'),str(pyreport)],capture_output=True,encoding='utf8',timeout=600)
   state['python']=json.loads(pyreport.read_text(encoding='utf8')) if pyreport.exists() else {'status':'failed','exit':run.returncode,'error':run.stderr}
   if run.returncode and state['python']['status']=='passed':state['python']['status']='failed'
   entryreport=Path(temporary)/'entrypoints.json'
   entryrun=subprocess.run([sys.executable,'-B','-X','utf8',str(worker),str(Path(__file__).resolve().parent),str(entryreport)],capture_output=True,encoding='utf8',timeout=60)
   state['entrypoints']=json.loads(entryreport.read_text(encoding='utf8')) if entryreport.exists() else {'status':'failed','exit':entryrun.returncode,'error':entryrun.stderr}
   if entryrun.returncode and state['entrypoints']['status']=='passed':state['entrypoints']['status']='failed'
   if not args.python_only:
    powershell=shutil.which('powershell') or shutil.which('pwsh')
    for name in ('test_render_powerpoint_background.ps1','test_delivery_render_warmup.ps1'):
     if not powershell:
      state['powershell'].append({'test':name,'status':'unavailable','reason':'PowerShell not installed'});continue
     child=subprocess.run([powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(runtime/'scripts'/name)],capture_output=True,encoding='utf8',timeout=180)
     state['powershell'].append({'test':name,'status':'passed' if child.returncode==0 else 'failed','exit':child.returncode,'detail':(child.stdout+child.stderr).strip() if child.returncode else ''})
   if args.visual_fixture:
    fixture=args.visual_fixture.resolve();fixture.parent.mkdir(parents=True,exist_ok=True)
    if fixture.exists():raise ValueError('Visual fixture already exists; choose a fresh destination')
    child=subprocess.run([sys.executable,'-B','-X','utf8',str(runtime/'scripts/test_complex_visuals.py'),str(fixture)],capture_output=True,encoding='utf8',timeout=120)
    if child.returncode or not fixture.is_file():raise RuntimeError('Fixture generation failed: '+child.stderr)
    state['visual_fixture']={'path':str(fixture),'status':'generated_pending_real_render_and_visual_review'}
  ok=state['python']['status']=='passed' and state['entrypoints']['status']=='passed' and all(x['status']=='passed' for x in state['powershell'])
  state['status']=('passed_python_only' if args.python_only else 'passed') if ok else 'failed_or_incomplete'
 except Exception as error:
  state['status']='failed';state['error']=type(error).__name__+': '+str(error)
 report.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'status':state['status'],'python_run':(state['python'] or {}).get('run'),'python_passed':(state['python'] or {}).get('passed'),'report':str(report)},ensure_ascii=False))
 return 0 if state['status'] in ('passed','passed_python_only') else 1
if __name__=='__main__':raise SystemExit(main())
