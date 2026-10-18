"""Exercise real background PowerPoint without modifying the supplied deck."""
from pathlib import Path
import argparse,sys,json,hashlib,shutil,subprocess,time
sys.dont_write_bytecode=True
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 base=Path(__file__).resolve().parent.parent
 ap.add_argument('--skill-root',type=Path,default=base/'skill/my-ppt-skill')
 ap.add_argument('--input',type=Path,default=base/'examples/01_scientific-charts/slides.pptx')
 ap.add_argument('--output',type=Path,required=True)
 a=ap.parse_args();root=a.skill_root.resolve();src=a.input.resolve();out=a.output.resolve()
 if not src.is_file() or not (root/'scripts/render_powerpoint_audit.ps1').is_file():
  print('Provide an existing --input PPTX and complete --skill-root.',file=sys.stderr);return 2
 if out.exists() or out.is_relative_to(root):
  print('Use a fresh --output directory outside the installed Skill.',file=sys.stderr);return 2
 powershell=shutil.which('powershell')
 if not powershell:
  print('This real integration check needs Windows PowerShell and installed desktop PowerPoint.',file=sys.stderr);return 2
 out.mkdir(parents=True);before=digest(src);candidate=out/'candidate.pptx';shutil.copy2(src,candidate)
 state={'status':'running','source_sha256':before,'attempts':[],'visual_signoff':False}
 code=1
 def run(command,stage):
  r=subprocess.run(command,capture_output=True,encoding='utf8',timeout=300)
  state['attempts'].append({'stage':stage,'exit':r.returncode,'diagnostic':(r.stdout+r.stderr).strip() if r.returncode else ''})
  return r
 try:
  from pptx import Presentation
  sys.path.insert(0,str(root/'scripts'))
  from pptx_delivery_shell import verify_shell
  from render_evidence import validate_render_evidence
  author=Presentation(candidate).core_properties.author
  command=[sys.executable,'-B','-X','utf8',str(root/'scripts/strip_pptx_metadata.py'),str(candidate)]
  if author:command+=['--author',author]
  if run(command,'metadata').returncode:raise RuntimeError('Metadata preparation failed')
  prep=[powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts/prepare_pptx_delivery.ps1'),'-InputPptx',str(candidate),'-OutputDir',str(out/'shell'),'-PythonExe',sys.executable,'-Width','1600']
  r=run(prep,'shell-1')
  if r.returncode and any(s in (r.stdout+r.stderr).lower() for s in ('800706b5','800706ba')):
   time.sleep(1);r=run(prep,'shell-2')
  if r.returncode:raise RuntimeError('First-slide preparation failed; inspect the current output evidence')
  prepared=digest(candidate);render=None;report=None
  for attempt in (1,2):
   render=out/f'render-{attempt}'
   r=run([powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts/render_powerpoint_audit.ps1'),'-InputPptx',str(candidate),'-OutputDir',str(render),'-Width','1600','-ExportPdf'],f'render-{attempt}')
   if digest(candidate)!=prepared:raise RuntimeError('Candidate changed during integration rendering')
   if (render/'audit.json').exists():report=json.loads((render/'audit.json').read_text(encoding='utf-8-sig'))
   if report and report.get('status') in ('rendered_pending_visual_review','failed_preflight'):
    if r.returncode and not (report.get('status')=='failed_preflight' and report.get('issues')):
     raise RuntimeError('Renderer returned a nonzero execution status despite a completed report; inspect cleanup/runtime failure before continuing')
    break
   if attempt==1 and any(s in (r.stdout+r.stderr).lower() for s in ('800706b5','800706ba')):time.sleep(1);continue
   raise RuntimeError('Real rendering did not complete; preserve failed evidence and fix the reported cause')
  validate_render_evidence(candidate,report,render,diagnostic_attempt=True)
  errors=verify_shell(candidate,render/'slide-01.png')
  if errors:raise RuntimeError('; '.join(errors))
  state.update(slides=report['slide_count'],candidate_sha256=prepared,preflight_issues=report['issues'],manual_review_count=len(report.get('manual_review',[])))
  state['status']='pipeline_checks_passed_visual_review_pending' if not report['issues'] else 'render_complete_rule_review_required'
  code=0 if not report['issues'] else 2
 except KeyboardInterrupt:
  state['status']='interrupted';code=130
 except Exception as error:
  state['status']='failed';state['error']=type(error).__name__+': '+str(error);code=1
 finally:
  try:source_unchanged=src.is_file() and digest(src)==before
  except OSError:source_unchanged=False
  if not source_unchanged:state['status']='failed';state['error']='Source file changed or became unavailable during the check';code=1
  (out/'integration-summary.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'status':state['status'],'slides':state.get('slides'),'report':str(out/'integration-summary.json')},ensure_ascii=False))
 return code
if __name__=='__main__':raise SystemExit(main())
