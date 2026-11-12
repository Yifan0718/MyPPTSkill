#!/usr/bin/env python3
"""Render slides with installed Microsoft PowerPoint; otherwise use LibreOffice.

Usage:
    python3 render_slides.py <input.pptx> <out_dir> [--dpi 144]

Output:
    <out_dir>/slide-<N>.png  (1-indexed, zero-padded)
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
import tempfile
import hashlib
import math
import json
import os
from pathlib import Path
from run_bounded import stop_owned_tree

def ms_powerpoint_installed():
    if sys.platform=='win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,r'PowerPoint.Application\CLSID'):return True
        except FileNotFoundError:pass
        for env in ('ProgramFiles','ProgramFiles(x86)'):
            base=os.environ.get(env)
            if base and any((Path(base)/rel).is_file() for rel in ('Microsoft Office/root/Office16/POWERPNT.EXE','Microsoft Office/Office16/POWERPNT.EXE')):return True
        return False
    if sys.platform=='darwin':return any(p.is_dir() for p in (Path('/Applications/Microsoft PowerPoint.app'),Path.home()/'Applications/Microsoft PowerPoint.app'))
    if sys.platform.startswith('linux') and (os.environ.get('WSL_DISTRO_NAME') or 'microsoft' in _kernel_release()):
        # Scientific work can run in WSL while installed Office belongs to Windows.
        for base in (Path('/mnt/c/Program Files'),Path('/mnt/c/Program Files (x86)')):
            if any((base/rel).is_file() for rel in ('Microsoft Office/root/Office16/POWERPNT.EXE','Microsoft Office/Office16/POWERPNT.EXE')):return True
        return _probe_windows_host()
    return False

def _kernel_release():
    try:return Path('/proc/sys/kernel/osrelease').read_text().lower()
    except OSError:return ''

def _probe_windows_host():
    shell=shutil.which('powershell.exe')
    if not shell:raise NativeOfficeRenderError('WSL cannot query the Windows host. Verify Office from the Windows runtime, then continue the corresponding native or confirmed-absent path.')
    command="$ErrorActionPreference='Stop'; try { if(Test-Path -LiteralPath 'Registry::HKEY_CLASSES_ROOT\\PowerPoint.Application\\CLSID'){exit 0}; foreach($base in @($env:ProgramFiles,${env:ProgramFiles(x86)})){if($base){foreach($rel in @('Microsoft Office/root/Office16/POWERPNT.EXE','Microsoft Office/Office16/POWERPNT.EXE')){if(Test-Path -LiteralPath (Join-Path $base $rel)){exit 0}}}}; exit 10 } catch { exit 11 }"
    try:probe=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
    except (OSError,subprocess.SubprocessError) as exc:raise NativeOfficeRenderError('Windows host Office detection failed; retry the native host query after repairing interop: '+str(exc)) from exc
    if probe.returncode==0:return True
    if probe.returncode==10:return False
    raise NativeOfficeRenderError('Windows host Office detection is uncertain (exit '+str(probe.returncode)+'); inspect native installation from Windows before selecting a renderer.')

class NativeOfficeRenderError(RuntimeError):
    def __init__(self,message,code=3):super().__init__(message);self.code=code

def _render_powerpoint(pptx,out_dir,dpi,timeout):
    if sys.platform!='win32':
        raise NativeOfficeRenderError('Microsoft PowerPoint is installed. Use its native export/automation for the current platform; in WSL run render_powerpoint_audit.ps1 through the Windows host runtime. Continue with Microsoft Office rather than switching to LibreOffice.')
    if out_dir.exists():raise ValueError('Use a fresh output directory')
    from pptx import Presentation
    from run_bounded import run
    count=len(Presentation(pptx).slides);width=round(Presentation(pptx).slide_width/12700*dpi/72)
    if not 320<=width<=10000:raise ValueError('Requested DPI produces a width outside the native renderer range 320–10000 px')
    script=Path(__file__).with_name('render_powerpoint_audit.ps1')
    code=run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-InputPptx',str(pptx.resolve()),'-OutputDir',str(out_dir.resolve()),'-Width',str(width),'-ExportPdf'],timeout,out_dir/'tool-run.json')
    if code:
        raise NativeOfficeRenderError('Microsoft PowerPoint returned '+str(code)+'. Read audit.json/tool-run.json, repair or visually reconcile the original finding, and continue the Office path. Rendered preflight candidates retain their original failure state.',2 if code==2 else 3)
    audit=json.loads((out_dir/'audit.json').read_text(encoding='utf-8-sig'))
    if audit.get('status')!='rendered_pending_visual_review' or audit.get('slide_count')!=count:
        raise NativeOfficeRenderError('Native Office output is incomplete; inspect the current audit and retry in a fresh directory.')
    pngs=sorted(out_dir.glob('slide-*.png'))
    if len(pngs)!=count or audit.get('sha256','').upper()!=hashlib.sha256(pptx.read_bytes()).hexdigest().upper():
        raise NativeOfficeRenderError('Native Office page count or source hash changed; retain this run and rerender a stable snapshot.')
    from PIL import Image
    for image in pngs:
        with Image.open(image) as im:im.verify()
    return pngs


def _run_converter(command,*,timeout,check=True,stdout=None,stderr=None,creationflags=0):
    if os.name=='nt':creationflags |= getattr(subprocess,'CREATE_NO_WINDOW',0)
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=creationflags,start_new_session=os.name!='nt')
    try:out,err=process.communicate(timeout=timeout)
    except BaseException:
        try:stop_owned_tree(process)
        except (OSError,subprocess.TimeoutExpired):pass
        raise
    if check and process.returncode:raise subprocess.CalledProcessError(process.returncode,command,output=out,stderr=err)
    return subprocess.CompletedProcess(command,process.returncode,out,err)


def render(pptx: Path, out_dir: Path, dpi: int = 144, timeout: float = 300) -> list[Path]:
    if dpi <= 0:raise ValueError('dpi must be positive')
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('timeout must be positive and finite')
    if ms_powerpoint_installed():return _render_powerpoint(pptx,out_dir,dpi,timeout)
    # A new output directory prevents old pages being mistaken for new renders.
    out_dir.mkdir(parents=True, exist_ok=False)
    original_hash=hashlib.sha256(pptx.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="pptrender_",ignore_cleanup_errors=True) as td:
        td_path = Path(td)
        snapshot=td_path/'input.pptx';shutil.copy2(pptx,snapshot)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=original_hash:
            raise RuntimeError('Input changed while taking snapshot')
        _run_converter(
            [
                "soffice",
                "-env:UserInstallation="+(td_path/"profile").as_uri(),
                "--headless",
                "--norestore",
                "--nologo",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(td_path),
                str(snapshot),
            ],
            check=True,
            timeout=timeout,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        pdf = snapshot.with_suffix('.pdf')
        if not pdf.is_file():
            raise RuntimeError('soffice did not produce the expected input.pdf for the current snapshot')
        _run_converter(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                str(pdf),
                str(out_dir / "slide"),
            ],
            check=True,
            timeout=timeout,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0,
        )
    pngs = sorted(out_dir.glob("slide-*.png"))
    from pptx import Presentation
    if len(pngs)!=len(Presentation(pptx).slides) or hashlib.sha256(pptx.read_bytes()).hexdigest()!=original_hash:
        raise RuntimeError('Page count mismatch or input changed during rendering')
    from PIL import Image
    if sorted(int(p.stem.split('-')[-1]) for p in pngs)!=list(range(1,len(pngs)+1)):
        raise RuntimeError('Rendered page numbering is incomplete')
    for image in pngs:
        with Image.open(image) as im:im.verify()
    return pngs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--dpi", type=int, default=144)
    ap.add_argument("--timeout",type=float,default=300,help="Maximum seconds for each conversion stage")
    args = ap.parse_args()
    try:pngs = render(args.pptx, args.out_dir, args.dpi,args.timeout)
    except Exception as error:
        print(json.dumps({'status':'failed','reason':type(error).__name__+': '+str(error),'recovery':'Check the installed Microsoft Office path first. When Office is installed, repair its native export/automation and use a fresh output directory; alternative Office-compatible suites apply only when Microsoft Office is absent. Retain original reports and continue the applicable visual review.'},ensure_ascii=True),file=sys.stderr)
        return error.code if isinstance(error,NativeOfficeRenderError) else 3
    print(f"Rendered {len(pngs)} slides → {args.out_dir}")
    for p in pngs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
