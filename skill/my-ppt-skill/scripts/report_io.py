"""Atomic audit reports that cannot overwrite input artifacts or frozen renders."""
from pathlib import Path
import json,os,sys,tempfile

def _same(a,b):
    if a.resolve()==b.resolve():return True
    try:return a.exists() and b.exists() and os.path.samefile(a,b)
    except OSError:return False

def evidence_files(inputs=(),frozen_dirs=()):
    """Read local metadata references only; data and raster payloads are leaves."""
    found=set();queue=[(Path(p),True) for p in inputs if p is not None];parsed=set()
    for root in frozen_dirs:
        root=Path(root)
        if root.is_dir():queue.extend((p,False) for p in root.rglob('*') if p.is_file())
    def walk(value,parent):
        if isinstance(value,dict):
            for key,item in value.items():
                path_key=(key in ('path','source','snapshot','baseline_pptx','baseline_signoff') or key.endswith(('_path','_file')))
                if path_key and isinstance(item,str) and item and '://' not in item:
                    path=Path(item);candidates=[path] if path.is_absolute() else [path,parent/path]
                    for candidate in candidates:
                        if candidate.is_file():queue.append((candidate,key not in ('source','source_path','source_data_path','crop_path','baseline_pptx')))
                walk(item,parent)
        elif isinstance(value,list):
            for item in value:walk(item,parent)
    while queue:
        path,follow=queue.pop();path=path.resolve();found.add(path)
        if follow and path.suffix.lower()=='.json' and path.is_file() and path not in parsed:
            parsed.add(path)
            try:value=json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):continue
            walk(value,path.parent)
    return found


def write_report(path,result,inputs=(),frozen_dirs=()):
    path=Path(path)
    for value in evidence_files(inputs,frozen_dirs):
        if _same(path,value):
            raise ValueError('Report path aliases an input artifact: '+str(path))
    for value in frozen_dirs:
        root=Path(value).resolve()
        # Render snapshots and source pixels are immutable evidence. Reports
        # belong beside the render folder, never inside it.
        if path.resolve().is_relative_to(root):
            raise ValueError('Report path is inside a frozen evidence directory: '+str(root))
        if path.exists() and root.is_dir():
            for source in root.iterdir():
                if source.is_file() and _same(path,source):
                    raise ValueError('Report path is a link to frozen evidence: '+str(source))
    if path.exists() and not path.is_file():raise ValueError('Report path is not a file: '+str(path))
    if path.suffix.lower()!='.json':raise ValueError('Use a .json report destination: '+str(path))
    payload=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as out:
            tmp=Path(out.name);out.write(payload);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None:
            try:tmp.unlink(missing_ok=True)
            except OSError:pass

def emit_report(path,result,inputs=(),frozen_dirs=()):
    """Return 0 after writing, or 3 with structured stderr recovery details."""
    try:
        write_report(path,result,inputs,frozen_dirs);return 0
    except Exception as error:
        try:safe_result=json.loads(json.dumps(result,default=str),parse_constant=str)
        except Exception:safe_result=repr(result)
        fallback={'status':'failed','stage':'report_write','report':str(path),
                  'error':type(error).__name__+': '+str(error),
                  'recovery':'Choose a new writable JSON report path outside input files and the render directory, then rerun the same check. Existing inputs and reports were retained.',
                  'check_result':safe_result}
        print(json.dumps(fallback,ensure_ascii=True,default=str),file=sys.stderr)
        return 3
