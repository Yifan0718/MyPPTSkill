#!/usr/bin/env python3
"""Check whether the local skill is up to date with the remote.

Reads:
  - <skill_root>/VERSION         current local version
  - <skill_root>/updates.json    update_source + history
  - remote updates.json          fetched from update_source/updates.json

Logic:
  1. If update_source is null/empty -> print "Update source unset" and exit 0.
  2. Otherwise GET <update_source>/updates.json (or git clone shallow if git+ URL).
  3. Compare remote.latest_version with local VERSION.
  4. If same -> "Up to date".
  5. If remote has newer versions, traverse remote.history from local version → latest,
     replay added/modified/removed paths in version order and list the result.

This script *does not* download files; it just reports what would change. Use
``apply_update.py`` to actually fetch/replace.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def parse_version(v: str) -> tuple[int, int, int]:
    if not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", v.strip()):
        raise ValueError('Version must have one to three nonnegative integer components')
    parts = [int(x) for x in v.strip().split('.')]
    return tuple(parts + [0] * (3-len(parts)))


def fetch_remote_updates(source: str) -> dict:
    if source.startswith("git+"):
        return _fetch_remote_updates_git(source)
    url = source.rstrip("/") + "/updates.json"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_remote_updates_git(source: str) -> dict:
    """For git+ sources: do a tiny shallow + blobless clone, read updates.json.

    LFS smudging is disabled so we don't pull large binary assets just to
    look at version metadata.
    """
    spec = source[4:]
    if "#" in spec:
        url, branch = spec.split("#", 1)
    else:
        url, branch = spec, "main"
    with tempfile.TemporaryDirectory(prefix="skillchk_") as td:
        env = os.environ.copy()
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
        env.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch,
             "--filter=blob:none", "--no-checkout", url, td],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        result = subprocess.run(["git", "show", "HEAD:updates.json"],
            cwd=td, check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,timeout=30)
        return json.loads(result.stdout.decode("utf-8-sig"))


def collect_delta(remote_hist: list[dict], local_version: str) -> tuple[set[str], set[str], set[str]]:
    """Replay releases in version order; later re-additions cancel removals."""
    local = parse_version(local_version)
    if not isinstance(remote_hist, list):raise ValueError('history must be an array')
    seen=set()
    for entry in remote_hist:
        if not isinstance(entry, dict):raise ValueError('history entries must be objects')
        version=parse_version(entry.get('version'))
        if version in seen:raise ValueError('Duplicate history version')
        seen.add(version)
        paths=set()
        for action in ('added','modified','removed'):
            values=entry.get(action,[])
            if not isinstance(values,list) or any(not isinstance(f,str) or not f.strip() for f in values):raise ValueError('File changes must be arrays of paths')
            if len(values)!=len(set(values)) or paths.intersection(values):raise ValueError('Duplicate/conflicting file change in release')
            paths.update(values)
    added: set[str] = set()
    modified: set[str] = set()
    removed: set[str] = set()
    for entry in sorted(remote_hist,key=lambda x:parse_version(x['version'])):
        if parse_version(entry["version"]) <= local:
            continue
        for f in entry.get("added", []):
            removed.discard(f);modified.discard(f)
            added.add(f)
        for f in entry.get("modified", []):
            removed.discard(f)
            if f not in added:modified.add(f)
        for f in entry.get("removed", []):
            added.discard(f);modified.discard(f)
            removed.add(f)
    return added, modified, removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = args.skill_root
    version_file = root / "VERSION"
    updates_file = root / "updates.json"

    if not version_file.exists() or not updates_file.exists():
        print("ERR  Cannot find VERSION or updates.json; this skill folder looks incomplete.",
              file=sys.stderr)
        return 2

    try:
        local_version = version_file.read_text(encoding="utf-8-sig").strip()
        parse_version(local_version)
        local_updates = json.loads(updates_file.read_text(encoding="utf-8-sig"))
        if not isinstance(local_updates,dict):raise ValueError('Local updates must be an object')
        source = local_updates.get("update_source")
        if source is not None and not isinstance(source,str):raise ValueError('update_source must be a string or null')
    except (OSError,ValueError,TypeError) as exc:
        print(f'ERR Invalid local metadata: {exc}',file=sys.stderr);return 4

    if not source:
        if not args.quiet:
            print("INFO Update source unset; skipping update check.")
            print(f"     Local version: {local_version}")
            print("     To enable updates, set updates.json -> update_source.")
        return 0

    try:
        remote = fetch_remote_updates(source)
    except (ValueError,UnicodeError) as exc:
        print(f'ERR Invalid remote metadata: {exc}',file=sys.stderr);return 4
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERR Update check failed ({exc}); remote version is unverified. Local files unchanged.", file=sys.stderr)
        return 3

    if not isinstance(remote, dict) or not remote.get("latest_version"):
        print("ERR Remote metadata lacks latest_version.", file=sys.stderr)
        return 4
    try:
        remote_latest = remote['latest_version']
        latest=parse_version(remote_latest)
        added, modified, removed = collect_delta(remote.get('history', []), local_version)
        versions=[parse_version(e['version']) for e in remote.get('history',[])]
        if any(v>latest for v in versions) or (latest>parse_version(local_version) and latest not in versions):raise ValueError('history does not support latest_version')
    except (ValueError,TypeError,KeyError) as exc:
        print(f'ERR Invalid remote metadata: {exc}',file=sys.stderr);return 4
    if parse_version(remote_latest) <= parse_version(local_version):
        print(f"OK   Up to date (local={local_version}, remote={remote_latest}).")
        return 0

    print(f"NEW  Update available: {local_version} -> {remote_latest}")
    print(f"     +{len(added)} added | ~{len(modified)} modified | -{len(removed)} removed")
    if added:
        print("\n     Added files:")
        for f in sorted(added):
            print(f"       + {f}")
    if modified:
        print("\n     Modified files:")
        for f in sorted(modified):
            print(f"       ~ {f}")
    if removed:
        print("\n     Removed files:")
        for f in sorted(removed):
            print(f"       - {f}")
    print(f"\n     To apply: python3 scripts/apply_update.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
