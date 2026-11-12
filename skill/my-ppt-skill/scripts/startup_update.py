"""Best-effort startup advice. Never downloads/applies an update or gates authoring.

0: startup advice returned (including unavailable checks); consult check_status.
130: user interrupted the command. Strict manual diagnostics remain check_update.py.
"""
from pathlib import Path
import argparse,json,math,os,subprocess,sys,time
from urllib.parse import urlparse
from check_update import parse_version,collect_delta

ROOT=Path(__file__).resolve().parent.parent
MAX_SECONDS=5.0
PER_SOURCE_SECONDS=2.0
MAX_BYTES=1024*1024
WORKER=r'''
import sys,json,urllib.request,http.client
r=json.loads(sys.stdin.read())
try:
 request=urllib.request.Request(r['url'],headers={'User-Agent':'MyPPTSkill-startup-update','Accept':'application/json'})
 with urllib.request.urlopen(request,timeout=r['timeout']) as response:
  size=response.headers.get('Content-Length')
  if response.headers.get('Transfer-Encoding','').lower()=='chunked':size=None
  declared=int(size) if size is not None else None
  if declared is not None and not 0<=declared<=r['limit']:raise ValueError('metadata size limit')
  data=response.read(r['limit']+1)
  if len(data)>r['limit']:raise ValueError('metadata size limit')
  if declared is not None and len(data)!=declared:raise ValueError('incomplete metadata')
  sys.stdout.buffer.write(data)
except Exception as e:
 print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(3)
'''

def fetch(url,timeout):
    if not isinstance(url,str) or urlparse(url).scheme not in ('http','https'):
        raise ValueError('Update metadata URL must use HTTP or HTTPS')
    request=json.dumps({'url':url,'timeout':timeout,'limit':MAX_BYTES}).encode('utf8')
    result=subprocess.run([sys.executable,'-I','-X','utf8','-c',WORKER],input=request,
        capture_output=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise OSError(result.stderr.decode('utf8',errors='replace').strip()[:1000] or 'metadata request failed')
    data=json.loads(result.stdout.decode('utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('Remote metadata must be an object')
    return data

def finish(checks,updates):
    status='updates_available' if updates else 'no_update' if checks and all(c['status']=='no_update' for c in checks) else 'check_unavailable'
    return {'schema':'myppt-startup-advice/v1','check_status':status,
        'workflow_action':'continue_local','should_prompt':bool(updates),
        'updates':updates,'checks':checks,'local_files_changed':False,
        'apply_authorized':False,'application_policy':'explicit_user_confirmation_then_guarded_update',
        'no_reply_action':'continue_local'}

def check_startup(root=ROOT,timeout=MAX_SECONDS):
    root=Path(root).resolve();started=time.monotonic();checks=[];updates=[]
    try:
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=MAX_SECONDS:
            raise ValueError('Startup budget must be positive and at most 5 seconds')
        config=json.loads((root/'startup-update.json').read_text(encoding='utf-8-sig'))
        if not isinstance(config,dict) or config.get('schema')!='myppt-startup-update/v1':
            raise ValueError('Invalid startup-update.json schema')
    except (OSError,ValueError,TypeError) as error:
        return finish([{'source':'configuration','status':'unavailable','error_code':4,'detail':str(error)}],[])
    sources=[('mypptskill','MYPPT_VERSION','release_metadata_url'),('upstream','VERSION','upstream_metadata_url')]
    for kind,filename,key in sources:
        row={'source':kind}
        try:
            local=(root/filename).read_text(encoding='utf-8-sig').strip();current=parse_version(local)
            row['local_version']=local
            url=config.get(key)
            if kind=='upstream':
                upstream=json.loads((root/'updates.json').read_text(encoding='utf-8-sig'))
                if not isinstance(upstream,dict) or not upstream.get('update_source') or upstream.get('update_source')!=config.get('upstream_source'):
                    row.update(status='unavailable',error_code=4,detail='Startup metadata source does not match the configured upstream update source');checks.append(row);continue
            if not url:
                row.update(status='unavailable',error_code=4,detail='Update source unset');checks.append(row);continue
            remaining=timeout-(time.monotonic()-started)
            if remaining<=0:
                row.update(status='unavailable',error_code=3,detail='Startup time budget exhausted');checks.append(row);continue
            data=fetch(url,min(PER_SOURCE_SECONDS,remaining))
            if kind=='mypptskill':
                if data.get('draft') is True or data.get('prerelease') is True:
                    row.update(status='unavailable',error_code=4,detail='Latest stable release unavailable');checks.append(row);continue
                remote=data.get('tag_name')
                if isinstance(remote,str):remote=remote.removeprefix('v')
                release_url='https://github.com/Yifan0718/MyPPTSkill/releases/tag/v'+str(remote)
            else:
                remote=data.get('latest_version')
                collect_delta(data.get('history',[]),local)
                if parse_version(remote)>current and not any(parse_version(e['version'])==parse_version(remote) for e in data.get('history',[])):
                    raise ValueError('Upstream history does not support latest_version')
                release_url='https://github.com/GordenSun/GordenPPTSkill'
            latest=parse_version(remote);row.update(remote_version=remote,status='update_available' if latest>current else 'no_update',error_code=0)
            if latest>current:
                updates.append({'source':kind,'local_version':local,'remote_version':remote,'url':release_url,
                    'apply_route':'review_myppt_release_candidate' if kind=='mypptskill' else 'guarded_upstream_update'})
        except (OSError,subprocess.SubprocessError) as error:
            row.update(status='unavailable',error_code=3,detail=type(error).__name__+': '+str(error)[:1000])
        except Exception as error:
            row.update(status='unavailable',error_code=4,detail=type(error).__name__+': '+str(error)[:1000])
        checks.append(row)
    result=finish(checks,updates);result['elapsed_seconds']=round(time.monotonic()-started,3)
    return result

def decision_action(advice,choice=None):
    """No choice, skip or absent update retains the installed version."""
    if choice=='update' and advice.get('should_prompt') is True and advice.get('updates'):
        return 'prepare_guarded_update'
    return 'continue_local'

def save_optional_report(path,root,result):
    if path is None:return
    try:
        path=Path(path).resolve()
        if path.is_relative_to(Path(root).resolve()):raise ValueError('Report must be outside the installed Skill')
        path.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation keeps prior evidence and configuration intact.
        with path.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    except (OSError,ValueError) as error:
        result['report_error']={'error_code':3,'detail':str(error),'workflow_action':'continue_local'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root',type=Path,default=ROOT)
    parser.add_argument('--timeout',type=float,default=MAX_SECONDS)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    try:
        result=check_startup(args.skill_root,args.timeout)
    except KeyboardInterrupt:
        print(json.dumps({'check_status':'cancelled','workflow_action':'cancelled'},ensure_ascii=False));return 130
    except Exception as error:
        result=finish([{'source':'startup','status':'unavailable','error_code':4,'detail':str(error)}],[])
    save_optional_report(args.report,args.skill_root,result)
    print(json.dumps(result,ensure_ascii=True))
    return 0

if __name__=='__main__':raise SystemExit(main())
