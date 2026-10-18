"""Freeze/check the rules, scripts and configuration used for a delivery run."""
from pathlib import Path
import argparse,hashlib,json
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent.parent
EXTENSIONS={'.md','.py','.ps1','.json','.yaml','.yml','.toml'}
def inventory(root):
    result={}
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if not p.is_file() or any(x in ('.git','__pycache__','local-overrides') for x in rel.parts):continue
        if p.suffix.lower() in EXTENSIONS or p.name=='VERSION':
            result[rel.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest().upper()
    return result

def snapshot(path,root=ROOT):
    if path.exists():raise ValueError('Skill lock already exists; retain it and use a new revision file')
    record={'schema':'gorden-skill-state/v1','root':str(root.resolve()),'created_utc':datetime.now(timezone.utc).isoformat(),'files':inventory(root)}
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    return record

def check(path,root=ROOT):
    record=json.loads(path.read_text(encoding='utf-8-sig'))
    if record.get('schema')!='gorden-skill-state/v1' or Path(record.get('root','')).resolve()!=root.resolve():raise ValueError('Invalid Skill lock or root mismatch')
    old=record.get('files');now=inventory(root)
    if not isinstance(old,dict) or not old:raise ValueError('Empty Skill inventory')
    changes=[k for k in sorted(set(old)|set(now)) if old.get(k)!=now.get(k)]
    return {'status':'changed' if changes else 'unchanged','changed_files':changes,'file_count':len(now)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['snapshot','check']);ap.add_argument('path',type=Path);a=ap.parse_args()
    try:
        if a.mode=='snapshot':r=snapshot(a.path);print(f"Frozen {len(r['files'])} Skill source/configuration files");return 0
        r=check(a.path);print(json.dumps(r,ensure_ascii=False));return 2 if r['changed_files'] else 0
    except Exception as exc:print(str(exc));return 3

if __name__=='__main__':raise SystemExit(main())
