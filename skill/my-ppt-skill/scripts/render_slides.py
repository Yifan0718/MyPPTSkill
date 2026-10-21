#!/usr/bin/env python3
"""Render every slide of a .pptx to PNG files using LibreOffice + pdftoppm.

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
        print(json.dumps({'status':'failed','reason':type(error).__name__+': '+str(error),'recovery':'Check the renderer and input, then use a fresh output directory. Increase --timeout for a large deck or switch to another available renderer; retained partial images are incomplete evidence.'},ensure_ascii=True),file=sys.stderr)
        return 3
    print(f"Rendered {len(pngs)} slides → {args.out_dir}")
    for p in pngs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
