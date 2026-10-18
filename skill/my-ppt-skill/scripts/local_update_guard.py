"""Stage upstream updates and preserve current and future local customizations."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, shutil, subprocess, difflib, sys, os, tempfile
from check_update import parse_version
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic_json(path,value):
    """Leave the previous valid metadata intact on interrupted writes."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',prefix=path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as stream:
            tmp=Path(stream.name)
            stream.write(json.dumps(value,ensure_ascii=False,indent=2).encode('utf8'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
def release_artifact_excluded(rel):
    """Development-only upstream files are not installed into a release tree."""
    p=PurePosixPath(rel)
    return (rel in ('CHANGELOG.md','.gitignore','.gitattributes') or
            (p.parent==PurePosixPath('scripts') and
             (p.name.startswith('test_') or p.suffix.lower()=='.pptx')))
def read(p,default): return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else default
def files(root):
    return {p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file() and not any(x in p.relative_to(root).parts for x in ('.git','__pycache__','local-overrides'))}
def safe(root,rel):
    if not isinstance(rel,str) or not rel or '\\' in rel or ':' in rel or any(x in ('','.', '..') for x in rel.split('/')) or PurePosixPath(rel).is_absolute():raise ValueError('Unsafe update path: '+str(rel))
    if any(x.lower() in ('local-overrides','.git','__pycache__') for x in rel.split('/')):raise ValueError('Reserved update path: '+rel)
    p=(root/rel).resolve()
    if not p.is_relative_to(root.resolve()):raise ValueError('Unsafe update path: '+rel)
    return p

def protection(root,live):
    """Keep registry tombstones and discover rules added/edited/deleted locally."""
    manifest=read(root/'manifest.json',{})
    if not isinstance(manifest,dict) or not isinstance(manifest.get('files',{}),dict):raise ValueError('Invalid manifest files')
    baseline=manifest.get('files',{})
    registry=read(root/'local-overrides/registry.json',{'protected_paths':[]})
    if not isinstance(registry,dict) or not isinstance(registry.get('protected_paths'),list):raise ValueError('Invalid local protection registry')
    paths=registry['protected_paths']
    for rel in paths:safe(root,rel)
    if len(paths)!=len(set(paths)):raise ValueError('Duplicate protected paths')
    protected=set(paths)|{'SKILL.md','references/local-delivery-quality.md','scripts/apply_update.py','scripts/local_update_guard.py'}
    for rel,entry in baseline.items():
        safe(root,rel)
        if not isinstance(entry,dict) or not isinstance(entry.get('sha256'),str):raise ValueError('Invalid manifest entry: '+rel)
    for rel in set(live)|set(baseline):
        if rel in ('manifest.json','VERSION'):continue
        if rel not in live or digest(live[rel])!=baseline.get(rel,{}).get('sha256'):protected.add(rel)
    return protected
def prepare(root,stage,candidate=None):
    root=root.resolve();stage=stage.resolve()
    if stage==root or root.is_relative_to(stage) or (stage.is_relative_to(root) and not stage.is_relative_to(root/'local-overrides')):
        raise ValueError('Stage must be outside the skill or inside local-overrides')
    if candidate and (stage.is_relative_to(candidate.resolve()) or candidate.resolve().is_relative_to(stage)):
        raise ValueError('Candidate and stage directories must not overlap')
    if stage.exists():raise ValueError('Stage must be a fresh directory')
    stage.mkdir(parents=True)
    live=files(root);protected=protection(root,live)
    for rel in protected:
        if rel not in live:continue
        dest=safe(stage/'local-snapshot',rel);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(live[rel],dest)
    (root/'local-overrides').mkdir(exist_ok=True)
    atomic_json(root/'local-overrides/registry.json',{'protected_paths':sorted(protected)})
    incoming=stage/'incoming'
    if candidate:shutil.copytree(candidate,incoming,ignore=shutil.ignore_patterns('.git','__pycache__','local-overrides'))
    else:
        source=read(root/'updates.json',{}).get('update_source','')
        if not source.startswith('git+'):
            raise ValueError('Automatic staging requires a git+ update_source; use --candidate for a reviewed local mirror')
        url,_,branch=source[4:].partition('#')
        env=os.environ.copy();env.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
        subprocess.run(['git','clone','--depth','1','--branch',branch or 'main',url,str(incoming)],check=True,timeout=180,env=env)
    new=files(incoming)
    if 'SKILL.md' not in new or 'VERSION' not in new:
        raise ValueError('Candidate must contain SKILL.md and VERSION')
    parse_version((root/'VERSION').read_text(encoding='utf-8-sig').strip())
    parse_version(new['VERSION'].read_text(encoding='utf-8-sig').strip())
    for rel in new:safe(root,rel)
    plan={'root':str(root.resolve()),'registry_sha256':digest(root/'local-overrides/registry.json'),'live_hashes':{k:digest(v) for k,v in live.items()},'incoming_hashes':{k:digest(v) for k,v in new.items()},'protected_paths':sorted(protected)}
    atomic_json(stage/'plan.json',plan)
    diffs=[]
    for rel,p in new.items():
        if p.suffix.lower() in ('.md','.py','.ps1','.json') and (rel not in live or digest(p)!=digest(live[rel])):
            old=live[rel].read_text(encoding='utf8',errors='replace').splitlines() if rel in live else []
            diffs.extend(difflib.unified_diff(old,p.read_text(encoding='utf8',errors='replace').splitlines(),fromfile='local/'+rel,tofile='upstream/'+rel,lineterm=''))
    (stage/'review.diff').write_text('\n'.join(diffs),encoding='utf8')
    atomic_json(stage/'review.json',{'status':'pending','conflicts':[],'reviewed_by':'','user_confirmation':''})
    print('STAGED ONLY. Read review.diff against current user rules. Live customizations are preserved.')
    return plan
def apply(root,stage):
    plan=read(stage/'plan.json',{});review=read(stage/'review.json',{})
    if not isinstance(plan,dict) or not isinstance(review,dict):raise ValueError('Invalid plan/review metadata')
    if str(root.resolve())!=plan.get('root'):raise ValueError('Root mismatch')
    status=review.get('status')
    if status not in ('approved_no_conflict','user_confirmed_resolution'):raise ValueError('Conflict review is pending; live update refused')
    if not review.get('reviewed_by'):raise ValueError('Reviewer is required')
    if (review.get('conflicts') or status=='user_confirmed_resolution') and (status!='user_confirmed_resolution' or not review.get('user_confirmation')):raise ValueError('Explicit user confirmation is required for identified conflicts')
    current=files(root);incoming=files(stage/'incoming')
    registry=root/'local-overrides/registry.json'
    if not registry.is_file() or digest(registry)!=plan.get('registry_sha256'):raise ValueError('Protection registry changed; restage to capture new rules')
    if {k:digest(v) for k,v in current.items()}!=plan['live_hashes']:raise ValueError('Local files changed; restage to capture new rules')
    if {k:digest(v) for k,v in incoming.items()}!=plan['incoming_hashes']:raise ValueError('Candidate changed; restage and review it')
    protected=protection(root,current)
    if not isinstance(plan.get('protected_paths'),list) or sorted(protected)!=plan['protected_paths']:raise ValueError('Protected paths changed or plan was altered; restage')
    for rel in incoming:safe(root,rel)
    touched=[];preview_refresh_required=[];shell_cleaned=[];release_skipped=[]
    atomic_json(stage/'result.json',{'status':'applying_not_complete'})
    try:
        # VERSION is committed last; all affected files are restored on failure.
        for rel in sorted(incoming,key=lambda x:(x=='VERSION',x)):
            if rel in protected:continue
            p=incoming[rel];dest=safe(root,rel);back=None
            if dest.exists():
                back=safe(stage/'rollback',rel);back.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,back)
            touched.append((dest,back))
            if release_artifact_excluded(rel):
                if dest.exists():dest.unlink()
                release_skipped.append(rel)
                continue
            # Upstream preview artwork is not evidence of the actual first page.
            # Keep existing protected previews; regenerate other previews from
            # the installed deck in the task workspace before showing them.
            if rel.startswith('templates/') and rel.endswith('/preview.png'):
                if dest.exists():dest.unlink()
                preview_refresh_required.append(rel)
                continue
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            if rel.startswith('templates/') and rel.lower().endswith('.pptx'):
                try:
                    from pptx_delivery_shell import clean_intermediate
                    clean_intermediate(dest)
                except Exception as exc:
                    raise RuntimeError('New template shell preparation failed; update will roll back. Use the configured Python runtime and a valid PPTX: '+str(exc)) from exc
                shell_cleaned.append(rel)
        for rel in protected:
            dest=safe(root,rel)
            if rel in plan['live_hashes']:
                if not dest.is_file() or digest(dest)!=plan['live_hashes'][rel]:raise RuntimeError('Protected file changed: '+rel)
            elif dest.exists():raise RuntimeError('Protected local deletion was resurrected: '+rel)
        if digest(registry)!=plan['registry_sha256']:raise RuntimeError('Protection registry changed during apply')
        result={'status':'applied','protected_paths':sorted(protected),'retained_removed_paths':sorted(set(current)-set(incoming)-protected),
                'shell_cleaned_templates':shell_cleaned,'first_slide_preview_refresh_required':preview_refresh_required,
                'release_artifacts_skipped':release_skipped}
        atomic_json(stage/'result.json',result)
    except BaseException as exc:
        rollback_errors=[]
        for dest,back in reversed(touched):
            try:
                if back:shutil.copy2(back,dest)
                else:dest.unlink(missing_ok=True)
            except BaseException as error:rollback_errors.append(type(error).__name__+': '+str(error))
        failure={'status':'rollback_failed' if rollback_errors else 'failed_rolled_back','error':str(exc),'rollback_errors':rollback_errors}
        try:atomic_json(stage/'result.json',failure)
        except Exception as report_error:
            print('ERR Cannot persist recovery status: '+str(report_error)+'; '+json.dumps(failure,ensure_ascii=False),file=sys.stderr)
        raise
    print('APPLIED. Protected files remain byte-identical; removed upstream files retained for review.')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',nargs='?',choices=['prepare','apply'],default='prepare');ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);ap.add_argument('--stage',type=Path);ap.add_argument('--candidate',type=Path)
    args=ap.parse_args();root=args.root.resolve()
    if args.stage:stage=args.stage.resolve()
    else:
        from datetime import datetime
        stage=root/'local-overrides'/'staged'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    try:
        if args.action=='prepare':prepare(root,stage,args.candidate)
        else:apply(root,stage)
        return 0
    except KeyboardInterrupt:
        print('ERR Update interrupted; inspect the stage result and restore any reported rollback failures before continuing.',file=sys.stderr)
        return 130
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
        print('ERR Update refused or failed: '+str(exc),file=sys.stderr)
        return 4
if __name__=='__main__':raise SystemExit(main())
