#!/usr/bin/env python3
"""Rebuild manifest.json with sha256 of every tracked file.

Tracked = everything in the skill root, EXCLUDING:
  - .work/, .duplicates/, __pycache__/, .DS_Store, hidden dirs
  - manifest.json itself
  - local-overrides/ (local protection state; never an upstream baseline)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from check_update import parse_version


EXCLUDE_DIRS = {".work", "__pycache__", ".git", ".idea", ".vscode", ".duplicates", "local-overrides"}
EXCLUDE_FILES = {".DS_Store", "manifest.json"}


def is_excluded_file(name: str) -> bool:
    if name in EXCLUDE_FILES:
        return True
    if name.startswith("~$"):  # PowerPoint/Office lock files
        return True
    return False


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in EXCLUDE_DIRS or part.startswith(".") for part in rel_parts[:-1]):
            continue
        if is_excluded_file(p.name):
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--version-tag", default=None,
                    help="If set, every newly-added entry's last_modified is recorded as this version")
    args = ap.parse_args()

    try:
        return build(args.skill_root,args.version_tag)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('ERR Manifest not rebuilt: '+str(exc),file=sys.stderr)
        return 4


def build(root: Path, version_tag=None) -> int:
    if (root/'local-overrides').exists():
        print('Refusing to rebase the upstream manifest of a locally customized install; use skill_state.py for local locks.',file=sys.stderr)
        return 2
    version = version_tag or (root / "VERSION").read_text(encoding="utf-8-sig").strip()
    parse_version(version)
    manifest_path = root / "manifest.json"

    old = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(previous,dict) or not isinstance(previous.get('files'),dict):raise ValueError('Invalid existing manifest files')
        old = previous['files']
        if any(not isinstance(v,dict) for v in old.values()):raise ValueError('Invalid existing manifest entry')

    files: dict[str, dict] = {}
    for p in iter_files(root):
        rel = p.relative_to(root).as_posix()
        sha = sha256_file(p)
        prev = old.get(rel, {})
        entry = {
            "sha256": sha,
            "size": p.stat().st_size,
            "version_added": prev.get("version_added", version),
            "last_modified": version if prev.get("sha256") != sha else prev.get("last_modified", version),
        }
        files[rel] = entry

    manifest = {
        "$schema": "ppt-skill-manifest/v1",
        "skill_name": "ppt-builder",
        "version": version,
        "file_count": len(files),
        "files": files,
    }
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=root,prefix='.manifest-',suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name)
            handle.write(json.dumps(manifest,ensure_ascii=False,indent=2))
        temporary.replace(manifest_path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    print(f"Wrote {manifest_path} (version={version}, files={len(files)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
