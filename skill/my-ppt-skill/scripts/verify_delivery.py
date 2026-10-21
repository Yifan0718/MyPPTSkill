"""Final evidence entry: run BOTH layout and audience gates; preserve every failure."""
from pathlib import Path
import argparse,json
from verify_coverage_review import verify as verify_layout
from verify_readability_review import verify as verify_audience,sha,load
from report_io import evidence_files
from skill_state import check as check_skill_state

def verify(pptx,coverage,review,render,audience):
    parts={};issues=[];fingerprints={}
    inputs=sorted(evidence_files([p for p in (pptx,coverage,review,audience) if p is not None]+[Path(render)/'audit.json'],[render]),key=str)
    for path in inputs:
        try:fingerprints[str(path)]=sha(path)
        except OSError as e:issues.append({'stage':'input','path':str(path),'reason':str(e)})
    before=fingerprints.get(str(Path(pptx).resolve()))
    for name,call in [('layout',lambda:verify_layout(pptx,coverage,load(review),render)),('audience',lambda:verify_audience(pptx,render,load(audience)))]:
        try:
            value=call()
            if not isinstance(value,dict):raise ValueError('Subcheck must return a structured result object')
            parts[name]=value
        except Exception as e:parts[name]={'status':'failed','issues':[type(e).__name__+': '+str(e)]}
        expected='evidence_complete_pending_visual_signoff' if name=='layout' else 'audience_evidence_complete_pending_semantic_signoff'
        if parts[name].get('status')!=expected or parts[name].get('issues')!=[]:issues.append({'stage':name,'details':parts[name]})
    after_inputs=evidence_files([p for p in (pptx,coverage,review,audience) if p is not None]+[Path(render)/'audit.json'],[render])
    if set(inputs)!=after_inputs:issues.append({'stage':'integrity','reason':'Evidence dependency paths changed during checks','added':[str(p) for p in sorted(after_inputs-set(inputs),key=str)],'removed':[str(p) for p in sorted(set(inputs)-after_inputs,key=str)]})
    for path in inputs:
        try:
            if sha(path)!=fingerprints.get(str(path)):issues.append({'stage':'integrity','path':str(path),'reason':'Input changed during final checks'})
        except OSError as e:issues.append({'stage':'integrity','path':str(path),'reason':str(e)})
    if review is not None:
        try:
            lock=load(review)['skill_lock']['path'];state=check_skill_state(Path(lock))
            if state['changed_files']:issues.append({'stage':'rules','reason':'Skill changed during delivery verification','files':state['changed_files']})
        except Exception as e:issues.append({'stage':'rules','reason':str(e)})
    return {'sha256':before,'status':'failed' if issues else 'evidence_complete_pending_visual_signoff','checks':parts,'issues':issues}

def main():
    ap=argparse.ArgumentParser();[ap.add_argument(n,type=Path) for n in ('pptx','coverage','review','render','audience','report')];a=ap.parse_args()
    try:r=verify(a.pptx,a.coverage,a.review,a.render,a.audience)
    except Exception as e:r={'status':'failed','issues':[{'stage':'execution','reason':str(e)}]}
    from report_io import emit_report
    report_error=emit_report(a.report,r,inputs=(a.pptx,a.coverage,a.review,a.audience),frozen_dirs=(a.render,))
    if report_error:return report_error
    print(r['status']);return 2 if r['issues'] else 0
if __name__=='__main__':raise SystemExit(main())
