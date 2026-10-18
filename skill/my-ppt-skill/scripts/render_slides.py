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
from pathlib import Path


def render(pptx: Path, out_dir: Path, dpi: int = 144) -> list[Path]:
    if dpi <= 0:raise ValueError('dpi must be positive')
    # A new output directory prevents old pages being mistaken for new renders.
    out_dir.mkdir(parents=True, exist_ok=False)
    original_hash=hashlib.sha256(pptx.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="pptrender_") as td:
        td_path = Path(td)
        snapshot=td_path/'input.pptx';shutil.copy2(pptx,snapshot)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=original_hash:
            raise RuntimeError('Input changed while taking snapshot')
        subprocess.run(
            [
                "soffice",
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        pdfs = list(td_path.glob("*.pdf"))
        if not pdfs:
            raise RuntimeError("soffice did not produce a PDF")
        pdf = pdfs[0]
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                str(pdf),
                str(out_dir / "slide"),
            ],
            check=True,
        )
    pngs = sorted(out_dir.glob("slide-*.png"))
    from pptx import Presentation
    if len(pngs)!=len(Presentation(pptx).slides) or hashlib.sha256(pptx.read_bytes()).hexdigest()!=original_hash:
        raise RuntimeError('Page count mismatch or input changed during rendering')
    return pngs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--dpi", type=int, default=144)
    args = ap.parse_args()
    pngs = render(args.pptx, args.out_dir, args.dpi)
    print(f"Rendered {len(pngs)} slides → {args.out_dir}")
    for p in pngs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
