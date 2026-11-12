#!/usr/bin/env python3
"""Validate exact fonts, configure TeX file paths, and install for this user.

Only Python's standard library is used. Exit 0: project and OS ready; 2:
project ready, OS unavailable/unverified (including --no-install); 1: invalid
bundle or project configuration failed. Only the pinned Fandol package may be
downloaded; --offline disables downloads. No other dependency is installed.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile

DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / 'assets/fonts/fonts.json'
ROLE_COMMANDS = {'main': 'setmainfont', 'sans': 'setsansfont',
                 'mono': 'setmonofont', 'cjk_main': 'setCJKmainfont',
                 'cjk_sans': 'setCJKsansfont', 'cjk_mono': 'setCJKmonofont',
                 'math': 'setmathfont'}
FANDOL_URLS = {'https://mirrors.ctan.org/fonts/fandol.zip',
              'https://ctan.math.illinois.edu/fonts/fandol.zip',
              'https://mirrors.ibiblio.org/pub/mirrors/CTAN/fonts/fandol.zip'}
TEX_MARKER = '% MyPPTSkill managed font configuration v1'
LEGACY_TEX_MARKER = '% Generated from the verified bundled font manifest.'
REPORT_SCHEMA = 'mypptskill.font-setup-report.v1'
DOWNLOAD_TOTAL_TIMEOUT = 60
DOWNLOAD_ATTEMPT_TIMEOUT = 20
LOCAL_FONT_LOOKUP_TIMEOUT = 20
OS_REGISTRATION_BUDGET = 60


class FontPreparationError(ValueError):
    """Expected preparation failure with actionable, serializable diagnostics."""
    def __init__(self, message, code='font_preparation_failed', recovery=None, diagnostics=None):
        super().__init__(message)
        self.code = code
        self.recovery = recovery or 'Retry with --cache-dir pointing to a new writable directory.'
        self.diagnostics = list(diagnostics or [])


DOWNLOAD_WORKER = r'''
import http.client, json, sys, urllib.request
request = json.loads(sys.stdin.read())
try:
    with urllib.request.urlopen(request['url'], timeout=10) as response:
        if not response.geturl().startswith('https://'):
            raise ValueError('Package redirect must remain HTTPS')
        count = 0
        with open(request['destination'], 'wb') as output:
            while True:
                chunk = response.read(131072)
                if not chunk:
                    break
                count += len(chunk)
                if count > request['size']:
                    raise ValueError('Font package exceeds manifest size')
                output.write(chunk)
        if count != request['size']:
            raise ValueError('Font package size mismatch')
except (OSError, ValueError, http.client.HTTPException) as exc:
    print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
    sys.exit(1)
'''


def _download_to_file(url, destination, size, timeout):
    """A killable process bounds DNS, redirects, headers, and slow body reads."""
    payload = json.dumps({'url': url, 'destination': str(destination), 'size': size})
    try:
        child = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', DOWNLOAD_WORKER], input=payload,
                               text=True, encoding='utf-8', capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        raise FontPreparationError('Font transport exceeded its wall-clock deadline',
                                   code='font_download_timeout',
                                   recovery='Retry online or supply a verified cache and use --offline.') from exc
    if child.returncode:
        detail = child.stderr.strip()[:2000] or 'Transport exited with code ' + str(child.returncode)
        raise FontPreparationError(detail, code='font_download_failed',
                                   recovery='Retry online; verified cached fonts can be used with --offline.')


def _cache_target(cache, target):
    """Limit recovery mutations to our known cache namespaces; never follow links."""
    cache, target = Path(cache).absolute(), Path(target).absolute()
    try:
        relative = target.relative_to(cache)
    except ValueError as exc:
        raise FontPreparationError('Recovery target is outside font cache', code='font_cache_unsafe') from exc
    if not relative.parts or not (relative.parts[0] in ('archives', 'packages', 'quarantine')
                                  or re.fullmatch(r'myppt-[a-f0-9]{16}', relative.parts[0])):
        raise FontPreparationError('Recovery target is not a managed font cache', code='font_cache_unsafe')
    cursor = cache
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or getattr(cursor, 'is_junction', lambda: False)():
            raise FontPreparationError('Linked font cache preserved: ' + str(cursor), code='font_cache_unsafe')
    if not target.resolve().is_relative_to(cache.resolve()):
        raise FontPreparationError('Recovery target escapes resolved cache', code='font_cache_unsafe')
    return target


def _quarantine_cache_file(cache, target, reason, diagnostics=None):
    target = _cache_target(cache, target)
    if not target.is_file():
        raise FontPreparationError('Non-file cache conflict preserved: ' + str(target), code='font_cache_conflict', diagnostics=diagnostics)
    folder = Path(cache) / 'quarantine' / uuid.uuid4().hex
    _cache_target(cache, folder)
    folder.mkdir(parents=True, exist_ok=False)
    saved = folder / target.name
    entry = {'action': 'quarantined', 'original': str(target), 'preserved': str(saved), 'reason': reason}
    try:
        target.rename(saved)
        (folder / 'recovery.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError as exc:
        raise FontPreparationError('Cannot quarantine managed cache: ' + str(exc),
                                   code='font_cache_recovery_failed', diagnostics=(diagnostics or []) + [entry]) from exc
    if diagnostics is not None:
        diagnostics.append(entry)
    return entry


def _publish_cache_file(cache, target, value, expected, diagnostics=None):
    """Publish verified bytes atomically; preserve damaged managed files first."""
    target = _cache_target(cache, target)
    if target.exists():
        if target.is_file() and digest(target) == expected:
            return
        _quarantine_cache_file(cache, target, 'SHA256 mismatch or interrupted cache write', diagnostics)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.myppt-stage-', dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            if isinstance(value, bytes):
                stream.write(value)
            else:
                with Path(value).open('rb') as source:
                    shutil.copyfileobj(source, stream)
        if digest(temporary) != expected:
            raise FontPreparationError('Staged cache failed SHA256 verification', code='font_cache_integrity', diagnostics=diagnostics)
        if target.exists():
            if target.is_file() and digest(target) == expected:
                return
            _quarantine_cache_file(cache, target, 'Concurrent damaged cache write', diagnostics)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def user_cache_directory():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'MyPPTSkill/fonts'
    if platform.system() == 'Darwin':
        return Path.home() / 'Library/Caches/MyPPTSkill/fonts'
    value = os.environ.get('XDG_CACHE_HOME')
    return (Path(value) if value and Path(value).is_absolute() else Path.home() / '.cache') / 'my-ppt-skill/fonts'


def safe_member(name, root):
    path = PurePosixPath(name)
    return bool(name and '\\' not in name and ':' not in name and not path.is_absolute()
                and not PureWindowsPath(name).drive and '..' not in path.parts
                and path.parts and path.parts[0] == root)


def download_package(package, cache, offline=False, diagnostics=None):
    expected = package.get('sha256', '')
    size = package.get('bytes')
    urls = package.get('urls') or [package.get('url')]
    if (not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)
            or type(size) is not int or not 0 < size <= 64 * 1024 * 1024
            or not urls or any(url not in FANDOL_URLS for url in urls)):
        raise ValueError('Only the pinned official Fandol HTTPS package is supported')
    diagnostics = diagnostics if diagnostics is not None else []
    archive = _cache_target(cache, Path(cache) / 'archives' / ('fandol-' + expected + '.zip'))
    if archive.exists():
        if archive.is_file() and archive.stat().st_size == size and digest(archive) == expected:
            return archive
        _quarantine_cache_file(cache, archive, 'Package cache size/SHA256 mismatch', diagnostics)
    if offline:
        raise FontPreparationError('Exact Fandol fonts/package unavailable in offline mode',
                                   code='font_offline_unavailable',
                                   recovery='Run again without --offline, or select a populated verified --cache-dir.',
                                   diagnostics=diagnostics)
    archive.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + DOWNLOAD_TOTAL_TIMEOUT
    errors = []
    timed_out = False
    for url in dict.fromkeys(urls):
        if time.monotonic() >= deadline:
            break
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.myppt-download-', dir=archive.parent, delete=False) as output:
                temporary = Path(output.name)
            _download_to_file(url, temporary, size, timeout=min(DOWNLOAD_ATTEMPT_TIMEOUT, max(0.001, deadline - time.monotonic())))
            if temporary.stat().st_size > size:
                raise ValueError('Font package exceeds manifest size')
            if temporary.stat().st_size != size or digest(temporary) != expected:
                raise ValueError('Font package size/SHA256 mismatch')
            _publish_cache_file(cache, archive, temporary, expected, diagnostics)
            return archive
        except (OSError, ValueError, http.client.HTTPException, subprocess.SubprocessError) as exc:
            timed_out = timed_out or isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) or getattr(exc, 'code', '') == 'font_download_timeout'
            errors.append(type(exc).__name__ + ': ' + str(exc))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise FontPreparationError('Font download failed: ' + '; '.join(errors),
                               code='font_download_timeout' if timed_out or time.monotonic() >= deadline else 'font_download_failed',
                               recovery='Retry online; a verified populated cache can be used with --offline.', diagnostics=diagnostics)


def extract_package(archive, package, package_fonts, cache, diagnostics=None):
    """Check every ZIP path and requested member hash before extracting any byte."""
    root = package.get('archive_root')
    if root != 'fandol' or digest(archive) != package['sha256']:
        raise ValueError('Invalid Fandol archive identity')
    directory = _cache_target(cache, Path(cache) / 'packages' / package['sha256'])
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        names = [info.filename for info in infos]
        if len(infos) > 2000 or sum(i.file_size for i in infos) > 256 * 1024 * 1024:
            raise ValueError('Font ZIP exceeds extraction limits')
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError('Duplicate ZIP member')
        for info in infos:
            if (not safe_member(info.filename, root) or not safe_member(info.orig_filename, root)
                    or '\x00' in info.orig_filename or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError('Unsafe ZIP member: ' + info.filename)
        selected = {}
        for font in package_fonts:
            name = font['file']
            if not safe_member(name, root):
                raise ValueError('Font member escapes ZIP root')
            value = zipped.read(name)
            if hashlib.sha256(value).hexdigest() != font['sha256']:
                raise ValueError('ZIP member SHA256 mismatch: ' + name)
            selected[name] = value
        for license_file in package.get('license_files', []):
            name = root + '/' + license_file
            if not safe_member(name, root):
                raise ValueError('License member escapes ZIP root')
            selected[name] = zipped.read(name)
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in selected.items():
        target = directory / name
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Cached ZIP path escapes extraction root')
        expected = hashlib.sha256(value).hexdigest()
        _publish_cache_file(cache, target, value, expected, diagnostics)
    return directory


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def existing_exact_font(name, sha256, timeout=10):
    """Reuse an existing identical TeX font; names alone never authorize reuse."""
    kpsewhich = shutil.which('kpsewhich')
    if kpsewhich:
        try:
            result = subprocess.run([kpsewhich, PurePosixPath(name).name],
                                    check=False, capture_output=True, text=True, errors='replace', timeout=timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in result.stdout.splitlines():
                candidate = Path(line.strip())
                if candidate.is_file() and digest(candidate) == sha256:
                    return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def load_manifest(path, cache_dir=None, offline=False):
    """Validate first, resolve exact fonts, then repair only managed cache files."""
    path = Path(path).resolve(strict=True)
    root = path.parent
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('fonts'), list) or not data['fonts']:
        raise ValueError('Expected schema_version=1 and a nonempty fonts list')
    cache = (Path(cache_dir) if cache_dir is not None else user_cache_directory()).absolute()
    seen, basenames = set(), set()
    for font in data['fonts']:
        if not isinstance(font, dict):
            raise ValueError('Each font entry must be an object')
        name = font.get('file', '')
        if not isinstance(name, str):
            raise ValueError('Font file must be a string')
        parts = PurePosixPath(name)
        if (not name or '\\' in name or parts.is_absolute() or PureWindowsPath(name).drive
                or '..' in parts.parts or not re.fullmatch(r'[A-Za-z0-9_.\-/]+', name)):
            raise ValueError('Unsafe bundled font path: ' + name)
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError('Font escapes bundle root: ' + name)
        if source.suffix.lower() not in ('.otf', '.ttf'):
            raise ValueError('Unsupported font file: ' + name)
        if name in seen or source.name.lower() in basenames:
            raise ValueError('Duplicate font file or basename: ' + name)
        seen.add(name)
        basenames.add(source.name.lower())
        expected = font.get('sha256', '')
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
            raise ValueError('Invalid SHA256: ' + name)
        if (source.exists() or font.get('distribution') != 'download') and (not source.is_file() or digest(source) != expected):
            raise ValueError('SHA256 mismatch: ' + name)
        for key in ('family', 'style', 'postscript_name'):
            if not isinstance(font.get(key), str) or not font[key].strip() or '\x00' in font[key]:
                raise ValueError('Missing/invalid font metadata: ' + key)
        font['_source'] = source
    roles = data.get('roles')
    if not isinstance(roles, dict) or set(roles) != set(ROLE_COMMANDS):
        raise ValueError('All seven explicit font roles are required')
    for role, faces in roles.items():
        if not isinstance(faces, dict) or not faces.get('regular'):
            raise ValueError('Missing regular face for ' + role)
        if set(faces) - {'regular', 'bold', 'italic', 'bold_italic'} or any(f not in seen for f in faces.values()):
            raise ValueError('Unknown role face for ' + role)
    if not isinstance(data.get('packages', {}), dict):
        raise ValueError('Manifest packages must be an object')
    diagnostics = []
    data['_cache_recovery'] = diagnostics
    runtime = cache / ('myppt-' + digest(path)[:16])
    extracted_packages = {}
    lookup_deadline = time.monotonic() + LOCAL_FONT_LOOKUP_TIMEOUT
    try:
        for font in data['fonts']:
            source = font['_source']
            if source.is_file():
                continue
            name, expected = font['file'], font['sha256']
            if font.get('package') != 'fandol':
                raise ValueError('Only Fandol may be downloaded')
            package = data.get('packages', {}).get('fandol', {})
            package_hash = package.get('sha256', '')
            candidates = [_cache_target(cache, runtime / PurePosixPath(name).name)]
            if isinstance(package_hash, str) and re.fullmatch('[a-f0-9]{64}', package_hash):
                candidates.append(_cache_target(cache, cache / 'packages' / package_hash / name))
            source = next((p for p in candidates if p.is_file() and digest(p) == expected), None)
            remaining = lookup_deadline - time.monotonic()
            if source is None and remaining > 0:
                source = existing_exact_font(name, expected, timeout=min(10, remaining))
            if source is None:
                extracted = extracted_packages.get('fandol')
                if extracted is None:
                    archive = download_package(package, cache, offline, diagnostics)
                    selected = [f for f in data['fonts'] if f.get('package') == 'fandol']
                    extracted = extract_package(archive, package, selected, cache, diagnostics)
                    extracted_packages['fandol'] = extracted
                source = extracted / name
            if not source.is_file() or digest(source) != expected:
                raise ValueError('Resolved font SHA256 mismatch: ' + name)
            font['_source'] = source
        # A previously interrupted configure_project must not poison all future runs.
        repairs = [(runtime / PurePosixPath(f['file']).name, f['_source'], f['sha256']) for f in data['fonts']]
        licenses = root / 'licenses'
        if licenses.is_dir():
            for source in licenses.rglob('*'):
                if source.is_file():
                    if not source.resolve().is_relative_to(root):
                        raise ValueError('License file escapes bundle root')
                    repairs.append((runtime / source.relative_to(root), source, digest(source)))
        for package in data.get('packages', {}).values():
            name = package.get('local_archive')
            if name:
                source = (root / name).resolve(strict=True)
                if not source.is_relative_to(root) or digest(source) != package['sha256']:
                    raise ValueError('Invalid bundled upstream archive: ' + name)
                repairs.append((runtime / 'upstream' / source.name, source, package['sha256']))
        # Source validation completes before any managed runtime font is replaced.
        for target, source, expected in repairs:
            _publish_cache_file(cache, target, source, expected, diagnostics)
        cached_manifest = _cache_target(cache, runtime / 'fonts.json')
        if cached_manifest.exists():
            try:
                json.loads(cached_manifest.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                _quarantine_cache_file(cache, cached_manifest, 'Interrupted or invalid cached manifest', diagnostics)
    except FontPreparationError as exc:
        if not exc.diagnostics:
            exc.diagnostics = list(diagnostics)
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, http.client.HTTPException) as exc:
        raise FontPreparationError(str(exc), code='font_cache_or_package_invalid', diagnostics=diagnostics) from exc
    return data


def copy_unchanged(source, target, expected):
    """Verify a staged file, then atomically publish without overwriting a user file."""
    target = Path(target)
    if target.is_symlink():
        raise ValueError('Refusing font destination symlink: ' + str(target))
    if target.exists():
        if target.is_file() and digest(target) == expected:
            return 'existing'
        raise ValueError('Existing different font preserved: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.myppt-copy-', dir=target.parent, delete=False) as dst:
            temporary = Path(dst.name)
            with Path(source).open('rb') as src:
                shutil.copyfileobj(src, dst)
        if digest(temporary) != expected:
            raise ValueError('Copied font failed SHA256 verification: ' + str(target))
        try:
            if os.name == 'nt':
                # Windows rename fails when destination already exists.
                os.rename(temporary, target)
            else:
                # Hard-link creation is atomic and has exclusive destination semantics.
                os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or digest(target) != expected:
                raise ValueError('Existing different font preserved: ' + str(target))
            return 'existing'
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 'copied'


def write_if_changed(path, text):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing configuration symlink: ' + str(path))
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def check_managed_tex(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing configuration symlink: ' + str(path))
    if path.exists():
        first_line = path.read_text(encoding='utf-8').splitlines()[:1]
        if not first_line or first_line[0] not in (TEX_MARKER, LEGACY_TEX_MARKER):
            raise ValueError('Existing user font configuration preserved: ' + str(path))


def check_report_path(path, manifest, project, cache_dir=None):
    path, manifest, project = Path(path), Path(manifest).resolve(), Path(project).resolve()
    resolved = path.resolve()
    cache = (Path(cache_dir) if cache_dir is not None else user_cache_directory()).resolve()
    # Reports never belong in the font inputs, cache, or generated TeX entry.
    if (resolved == project / 'myppt-fonts.tex' or resolved == manifest
            or resolved.is_relative_to(manifest.parent) or resolved.is_relative_to(cache)
            or resolved.suffix.lower() != '.json' or path.is_symlink()):
        raise ValueError('Report path collides with a protected input/configuration: ' + str(path))
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise ValueError('Existing unrelated report target preserved: ' + str(path)) from exc
        if not isinstance(previous, dict) or previous.get('report_schema') != REPORT_SCHEMA:
            raise ValueError('Existing unrelated report target preserved: ' + str(path))


def configure_project(data, manifest, project, cache_dir=None):
    project = Path(project).resolve()
    check_managed_tex(project / 'myppt-fonts.tex')
    project.mkdir(parents=True, exist_ok=True)
    cache = (Path(cache_dir) if cache_dir is not None else user_cache_directory()).resolve()
    directory = cache / ('myppt-' + digest(manifest)[:16])
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(cache):
        raise ValueError('Font directory escapes cache')
    font_path = directory.as_posix()
    if any(c in font_path for c in '%#{}^~\r\n'):
        raise ValueError('Cache path contains TeX-reserved characters; select --cache-dir')
    for font in data['fonts']:
        copy_unchanged(font['_source'], directory / PurePosixPath(font['file']).name, font['sha256'])
    bundle_root = Path(manifest).resolve().parent
    license_root = bundle_root / 'licenses'
    if license_root.is_dir():
        for source in license_root.rglob('*'):
            if source.is_file():
                if not source.resolve().is_relative_to(bundle_root):
                    raise ValueError('License file escapes bundle root')
                target = directory / source.relative_to(bundle_root)
                copy_unchanged(source, target, digest(source))
    for package in data.get('packages', {}).values():
        local_archive = package.get('local_archive')
        if not local_archive:
            continue
        source = (bundle_root / local_archive).resolve(strict=True)
        if not source.is_relative_to(bundle_root) or digest(source) != package['sha256']:
            raise ValueError('Invalid bundled upstream archive: ' + local_archive)
        target = directory / 'upstream' / source.name
        copy_unchanged(source, target, package['sha256'])
    lines = [TEX_MARKER, r'\RequirePackage{fontspec}',
             r'\ifdefined\setCJKmainfont\else',
             r'  \RequirePackage[fontset=none]{ctex}', r'\fi']
    keys = {'bold': 'BoldFont', 'italic': 'ItalicFont', 'bold_italic': 'BoldItalicFont'}
    for role, command in ROLE_COMMANDS.items():
        faces = data['roles'][role]
        options = ['Path={' + font_path + '/}']
        if role != 'math':
            # Explicitly map absent variants to a supplied face, never family lookup.
            for key, option in keys.items():
                value = faces.get(key, faces.get('italic', faces['regular']) if key == 'bold_italic' else faces['regular'])
                options.append(option + '={' + PurePosixPath(value).name + '}')
        selection = '\\' + command + '[' + ','.join(options) + ']{' + PurePosixPath(faces['regular']).name + '}'
        if role == 'math':
            # Only the caller may opt into unicode-math and change the math backend.
            lines.append(r'\providecommand{\MyPPTUseBundledMathFont}{' + selection + '}')
        else:
            lines.append(selection)
    lines.append(r'\def\MyPPTBundledFontsLoaded{1}')
    write_if_changed(project / 'myppt-fonts.tex', '\n'.join(lines) + '\n')
    clean = {key: value for key, value in data.items() if key != 'fonts' and not key.startswith('_')}
    clean['fonts'] = [{k: v for k, v in f.items() if not k.startswith('_')} for f in data['fonts']]
    write_if_changed(directory / 'fonts.json', json.dumps(clean, ensure_ascii=False, indent=2) + '\n')
    return project, directory


def user_font_directory(system, environ=None, home=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if system == 'Windows':
        value = environ.get('LOCALAPPDATA')
        if not value or not Path(value).is_absolute():
            raise ValueError('LOCALAPPDATA is missing or not absolute')
        return Path(value) / 'Microsoft/Windows/Fonts'
    if system == 'Darwin':
        return home / 'Library/Fonts'
    if system == 'Linux':
        value = environ.get('XDG_DATA_HOME')
        base = Path(value) if value and Path(value).is_absolute() else home / '.local/share'
        return base / 'fonts/MyPPTSkill'
    raise ValueError('Unsupported user-font platform: ' + system)


def windows_family_available(family, full_name=None, style=None):
    """Enumerate real GDI faces; optional full-name/style verifies a specific face."""
    from ctypes import wintypes as wt
    class LOGFONT(ctypes.Structure):
        _fields_ = [('height', wt.LONG), ('width', wt.LONG), ('escapement', wt.LONG),
                    ('orientation', wt.LONG), ('weight', wt.LONG),
                    ('italic', wt.BYTE), ('underline', wt.BYTE), ('strikeout', wt.BYTE),
                    ('charset', wt.BYTE), ('outprecision', wt.BYTE), ('clipprecision', wt.BYTE),
                    ('quality', wt.BYTE), ('pitch', wt.BYTE), ('face', wt.WCHAR * 32)]
    class ENUMLOGFONTEX(ctypes.Structure):
        _fields_ = [('font', LOGFONT), ('full_name', wt.WCHAR * 64),
                    ('style', wt.WCHAR * 32), ('script', wt.WCHAR * 32)]
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    gdi.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi.CreateCompatibleDC.restype = wt.HDC
    gdi.DeleteDC.argtypes = [wt.HDC]
    found = []
    expected_names = (full_name,) if isinstance(full_name, str) else (full_name or ())
    expected_styles = (style,) if isinstance(style, str) else (style or ())
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(LOGFONT), ctypes.c_void_p, wt.DWORD, wt.LPARAM)
    def visit(logfont, metrics, font_type, param):
        face = ctypes.cast(logfont, ctypes.POINTER(ENUMLOGFONTEX)).contents
        same_face = ((not expected_names and not expected_styles)
                     or face.full_name.casefold() in {v.casefold() for v in expected_names}
                     or face.style.casefold() in {v.casefold() for v in expected_styles})
        if face.font.face.casefold() == family.casefold() and same_face:
            found.append(True)
        return 1
    callback = callback_type(visit)
    query = LOGFONT()
    query.charset = 1  # DEFAULT_CHARSET
    query.face = family[:31]
    gdi.EnumFontFamiliesExW.argtypes = [wt.HDC, ctypes.POINTER(LOGFONT), callback_type, wt.LPARAM, wt.DWORD]
    dc = gdi.CreateCompatibleDC(None)
    if not dc:
        raise OSError('CreateCompatibleDC failed')
    try:
        gdi.EnumFontFamiliesExW(dc, ctypes.byref(query), callback, 0, 0)
    finally:
        gdi.DeleteDC(dc)
    return bool(found)


def windows_font_name(source, fallback, name_id=1):
    """Read a Windows SFNT name, independently of typographic-family metadata."""
    raw = Path(source).read_bytes()
    if len(raw) < 12:
        return fallback
    count = struct.unpack_from('>H', raw, 4)[0]
    for index in range(count):
        offset = 12 + index * 16
        if offset + 16 > len(raw):
            return fallback
        tag, checksum, start, length = struct.unpack_from('>4sIII', raw, offset)
        if tag != b'name' or start + length > len(raw) or length < 6:
            continue
        table = raw[start:start + length]
        _, records, strings = struct.unpack_from('>HHH', table)
        matches = []
        for row in range(records):
            if 6 + (row + 1) * 12 > len(table):
                break
            plat, encoding, language, nameid, size, pos = struct.unpack_from('>HHHHHH', table, 6 + row * 12)
            if plat == 3 and nameid == name_id and strings + pos + size <= len(table):
                value = table[strings + pos:strings + pos + size].decode('utf-16-be', errors='replace')
                matches.append((language != 0x409, value))
        if matches:
            return sorted(matches)[0][1]
    return fallback


def windows_font_family(source, fallback):
    return windows_font_name(source, fallback, 1)


def install_windows(font, destination):
    import winreg
    from ctypes import wintypes as wt
    value_name = font['postscript_name'] + ' (OpenType)'
    family = windows_font_family(destination, font['family'])
    full_name = windows_font_name(destination, font['postscript_name'], 4)
    style = windows_font_name(destination, font['style'], 2)
    registry = r'Software\Microsoft\Windows NT\CurrentVersion\Fonts'
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            old, kind = winreg.QueryValueEx(key, value_name)
        except FileNotFoundError:
            old = None
        if old is not None and (not isinstance(old, str) or os.path.normcase(os.path.abspath(old)) != os.path.normcase(str(destination))):
            raise ValueError('Existing different font registry entry preserved: ' + value_name)
        if old is None:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(destination))
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    gdi.AddFontResourceExW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p]
    gdi.AddFontResourceExW.restype = ctypes.c_int
    names = (full_name, font['postscript_name'])
    styles = (style, font['style'])
    existing_face = old is not None and windows_family_available(family, names, styles)
    count = 0 if existing_face else gdi.AddFontResourceExW(str(destination), 0, None)
    face_available = windows_family_available(family, names, styles)
    installed = bool(count > 0 or existing_face)
    return {'configured': True, 'installed': installed,
            'os_available': bool(installed and face_available),
            'method': 'HKCU+AddFontResourceExW+GDI full-name/style enumeration',
            'native_result': count, 'windows_family': family, 'windows_full_name': full_name,
            'windows_style': style, 'face_verified': face_available, 'application_refresh_required': True}


def broadcast_windows_change():
    from ctypes import wintypes as wt
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
                                        wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = wt.LPARAM
    result = ctypes.c_size_t()
    # Bounded broadcast; no application can indefinitely block setup.
    return bool(user.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002 | 0x0020, 1000, ctypes.byref(result)))


def install_linux(font, destination):
    cache, match = shutil.which('fc-cache'), shutil.which('fc-match')
    if not cache or not match:
        return {'configured': False, 'installed': False, 'os_available': False,
                'method': 'fontconfig unavailable', 'error': 'fc-cache and fc-match are required to verify OS availability'}
    subprocess.run([cache, str(destination.parent)], check=True, capture_output=True, timeout=20)
    # PostScript matching plus exact file hash rejects substituted/different versions.
    result = subprocess.run([match, '-f', '%{file}\n', ':postscriptname=' + font['postscript_name']],
                            check=True, capture_output=True, text=True, timeout=10)
    matched = Path(result.stdout.strip().splitlines()[0]) if result.stdout.strip() else None
    available = bool(matched and matched.is_file() and digest(matched) == font['sha256'])
    return {'configured': True, 'installed': available, 'os_available': available,
            'method': 'fontconfig cache+exact matched file SHA256',
            'application_refresh_required': True}


def install_macos(font, destination):
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    ct = ctypes.CDLL('/System/Library/Frameworks/CoreText.framework/CoreText')
    ptr = ctypes.c_void_p
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ptr, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
    cf.CFURLCreateFromFileSystemRepresentation.restype = ptr
    cf.CFURLGetFileSystemRepresentation.argtypes = [ptr, ctypes.c_bool, ctypes.c_char_p, ctypes.c_long]
    cf.CFURLGetFileSystemRepresentation.restype = ctypes.c_bool
    cf.CFStringCreateWithCString.argtypes = [ptr, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ptr
    cf.CFStringGetCString.argtypes = [ptr, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ptr]
    ct.CTFontManagerRegisterFontsForURL.argtypes = [ptr, ctypes.c_uint32, ctypes.POINTER(ptr)]
    ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
    ct.CTFontCreateWithName.argtypes = [ptr, ctypes.c_double, ptr]
    ct.CTFontCreateWithName.restype = ptr
    ct.CTFontCopyPostScriptName.argtypes = [ptr]
    ct.CTFontCopyPostScriptName.restype = ptr
    ct.CTFontCopyAttribute.argtypes = [ptr, ptr]
    ct.CTFontCopyAttribute.restype = ptr
    raw = os.fsencode(destination)
    url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
    name = cf.CFStringCreateWithCString(None, font['postscript_name'].encode(), 0x08000100)
    error = ptr()
    objects = [url, name]
    try:
        registered = ct.CTFontManagerRegisterFontsForURL(url, 2, ctypes.byref(error))
        face = ct.CTFontCreateWithName(name, 12, None)
        objects.append(face)
        actual_name = ct.CTFontCopyPostScriptName(face) if face else None
        objects.append(actual_name)
        buffer = ctypes.create_string_buffer(512)
        name_matches = bool(actual_name and cf.CFStringGetCString(actual_name, buffer, len(buffer), 0x08000100)
                            and buffer.value.decode() == font['postscript_name'])
        actual_url = ct.CTFontCopyAttribute(face, ptr.in_dll(ct, 'kCTFontURLAttribute')) if face else None
        objects.append(actual_url)
        path_buffer = ctypes.create_string_buffer(32768)
        actual_path = None
        if actual_url and cf.CFURLGetFileSystemRepresentation(actual_url, True, path_buffer, len(path_buffer)):
            actual_path = Path(os.fsdecode(path_buffer.value))
        available = bool(name_matches and actual_path and actual_path.is_file() and digest(actual_path) == font['sha256'])
        return {'configured': True, 'installed': available, 'os_available': available,
                'native_result': bool(registered), 'method': 'user Library/Fonts+CoreText PostScript and exact file SHA256',
                'application_refresh_required': True}
    finally:
        for obj in objects + [error.value]:
            if obj:
                cf.CFRelease(obj)


def install_native(font, destination, system):
    return {'Windows': install_windows, 'Linux': install_linux, 'Darwin': install_macos}[system](font, destination)


def export_bootstrap(manifest, project_dir):
    """Export only public inputs and an independent stdlib preparation entry."""
    manifest, project = Path(manifest).resolve(strict=True), Path(project_dir).resolve()
    bundle = manifest.parent
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('fonts'), list):
        raise ValueError('Invalid bootstrap manifest')
    sources = {'fonts.json': manifest}
    for font in data['fonts']:
        if font.get('distribution') == 'download':
            continue
        name = font['file']
        if (not isinstance(name, str) or '\\' in name or PurePosixPath(name).is_absolute()
                or PureWindowsPath(name).drive or '..' in PurePosixPath(name).parts):
            raise ValueError('Unsafe bootstrap font path')
        source = (bundle / name).resolve(strict=True)
        if not source.is_relative_to(bundle) or digest(source) != font['sha256']:
            raise ValueError('Bootstrap font hash/path mismatch: ' + name)
        sources[name] = source
    for package in data.get('packages', {}).values():
        name = package.get('local_archive')
        if package.get('distribution') == 'download' or not name:
            continue
        source = (bundle / name).resolve(strict=True)
        if not source.is_relative_to(bundle) or digest(source) != package['sha256']:
            raise ValueError('Bootstrap upstream archive hash/path mismatch')
        sources[name] = source
    licenses = bundle / 'licenses'
    if licenses.is_dir():
        for source in licenses.rglob('*'):
            if source.is_file():
                if not source.resolve().is_relative_to(bundle):
                    raise ValueError('Bootstrap license escapes bundle root')
                sources[source.relative_to(bundle).as_posix()] = source
    for source in bundle.iterdir():
        if source.is_file() and source.name.lower().startswith(('readme', 'license')):
            if not source.resolve().is_relative_to(bundle):
                raise ValueError('Bootstrap notice escapes bundle root')
            sources[source.name] = source
    script = Path(__file__).resolve()
    records = [(project / 'font-support/scripts/setup_fonts.py', script)]
    records += [(project / 'font-support/assets/fonts' / name, source) for name, source in sources.items()]
    launcher = ("#!/usr/bin/env python3\n"
                '"""Prepare exact presentation fonts using the accompanying public resources."""\n'
                'from pathlib import Path\nimport runpy\nimport sys\n\n'
                'root = Path(__file__).resolve().parent\n'
                'script = root / "font-support/scripts/setup_fonts.py"\n'
                'sys.argv = [str(script), "--project-dir", str(root), *sys.argv[1:]]\n'
                'runpy.run_path(str(script), run_name="__main__")\n').encode('utf-8')
    records.append((project / 'prepare-fonts.py', launcher))
    # Check every destination first, preserving the entire existing project on conflict.
    for target, source in records:
        expected = hashlib.sha256(source).hexdigest() if isinstance(source, bytes) else digest(source)
        if not target.resolve().is_relative_to(project) or target.is_symlink():
            raise ValueError('Bootstrap destination escapes project: ' + str(target))
        if target.exists() and (not target.is_file() or digest(target) != expected):
            raise ValueError('Existing different bootstrap file preserved: ' + str(target))
    for target, source in records:
        if isinstance(source, bytes):
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(source)
        else:
            copy_unchanged(source, target, digest(source))
    return {'schema_version': 1, 'report_schema': 'mypptskill.font-bootstrap-export.v1',
            'exported': True, 'installed': False, 'project_dir': str(project),
            'files': [str(target.relative_to(project)) for target, _ in records], 'exit_status': 0}


def setup_fonts(manifest=DEFAULT_MANIFEST, project_dir='.', install=True, system=None, offline=False, cache_dir=None):
    system = platform.system() if system is None else system
    report = {'schema_version': 1, 'report_schema': REPORT_SCHEMA,
              'platform': system, 'project_local': False, 'cache_ready': False,
              'configured': False, 'installed': False, 'os_available': False,
              'application_refresh_required': False, 'fonts': [], 'errors': [],
              'stage': 'resource-preparation'}
    try:
        check_managed_tex(Path(project_dir).resolve() / 'myppt-fonts.tex')
        data = load_manifest(manifest, cache_dir, offline)
        report['cache_recovery'] = data.get('_cache_recovery', [])
        project, directory = configure_project(data, manifest, project_dir, cache_dir)
        report.update(cache_ready=True, configured=True, project_dir=str(project),
                      tex_file=str(project / 'myppt-fonts.tex'), font_dir=str(directory),
                      font_files=[{'path': str(directory / PurePosixPath(f['file']).name), 'sha256': f['sha256']} for f in data['fonts']],
                      bundle_sha256=digest(manifest))
    except Exception as exc:
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
        report['exit_status'] = 1
        report['recovery'] = [
            'Use the recorded cause: restore the pinned resources or connectivity; rerun once after that change.',
            'For an unwritable or conflicting cache use --cache-dir with a new writable directory; preserve user font/configuration files.',
            'Offline mode requires identical local fonts or the validated official archive; prepare these before retrying.',
            'Keep the content plan and work on writing/data while restoring fonts; resume build and visual review with the original content.']
        if getattr(exc, 'code', None):
            report['error_code'] = exc.code
        if getattr(exc, 'recovery', None):
            actions = exc.recovery if isinstance(exc.recovery, list) else [str(exc.recovery)]
            report['recovery'] = actions + report['recovery']
        if getattr(exc, 'diagnostics', None):
            report['cache_recovery'] = exc.diagnostics
        return report
    report['stage'] = 'os-registration'
    try:
        target_dir = user_font_directory(system) if install else None
    except Exception as exc:
        target_dir = None
        report['errors'].append(str(exc))
    registration_deadline = time.monotonic() + OS_REGISTRATION_BUDGET
    for font in data['fonts']:
        item = {k: font[k] for k in ('file', 'family', 'style', 'postscript_name', 'sha256')}
        item.update(project_local=False, cache_ready=True, configured=False, installed=False, os_available=False)
        if target_dir is not None and time.monotonic() >= registration_deadline:
            item['error'] = 'OS registration time budget reached; exact cache remains ready.'
        elif target_dir is not None:
            basename = PurePosixPath(font['file']).name
            destination = target_dir / basename
            try:
                # Recheck exact cached bytes before handing them to the OS.
                item['copy_status'] = copy_unchanged(directory / basename, destination, font['sha256'])
                item['destination'] = str(destination)
                item.update(install_native(font, destination, system))
            except Exception as exc:
                item['error'] = type(exc).__name__ + ': ' + str(exc)
        else:
            item['error'] = 'OS installation disabled' if not install else 'No supported user-font directory'
        report['fonts'].append(item)
    if install and system == 'Windows' and any(f['configured'] for f in report['fonts']):
        try:
            report['fontchange_broadcast'] = broadcast_windows_change()
        except Exception as exc:
            report['errors'].append(str(exc))
    report['installed'] = all(f['installed'] for f in report['fonts'])
    report['os_available'] = all(f['os_available'] for f in report['fonts'])
    report['application_refresh_required'] = any(f.get('application_refresh_required', False) for f in report['fonts'])
    report['exit_status'] = 0 if report['installed'] and report['os_available'] else 2
    report['stage'] = 'complete'
    report['recovery'] = ([] if report['exit_status'] == 0 else [
        'Exact cache/configuration is ready: continue TeX file loading.',
        'For PowerPoint inspect per-font errors, restore user-font registration, then render to verify actual faces.'])
    return report


class FontArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = FontArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--project-dir', type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', dest='install', action='store_true', default=True)
    group.add_argument('--no-install', dest='install', action='store_false')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--offline', action='store_true', help='Use only bundled, cached, or identical existing fonts')
    parser.add_argument('--cache-dir', type=Path, help='User cache override; generated TeX uses its absolute path')
    parser.add_argument('--export-bootstrap', action='store_true',
                        help='Export independent preparation scripts/public resources only; no installation or network')
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        print('Invalid font setup arguments: ' + str(exc), file=sys.stderr)
        return 1
    if args.export_bootstrap:
        try:
            if args.report:
                raise ValueError('--report is not used with --export-bootstrap')
            exported = export_bootstrap(args.manifest, args.project_dir)
        except Exception as exc:
            print('Cannot export font bootstrap: ' + str(exc), file=sys.stderr)
            return 1
        print(json.dumps(exported, ensure_ascii=False, indent=2))
        return 0
    report_path = args.report or args.project_dir / 'font-setup-report.json'
    try:
        check_report_path(report_path, args.manifest, args.project_dir, args.cache_dir)
    except Exception as exc:
        print('Cannot write font setup report: ' + str(exc), file=sys.stderr)
        return 1
    report = setup_fonts(args.manifest, args.project_dir, args.install, offline=args.offline, cache_dir=args.cache_dir)
    output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    try:
        check_report_path(report_path, args.manifest, args.project_dir, args.cache_dir)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_if_changed(report_path, output)
    except Exception as exc:
        print('Cannot write font setup report: ' + str(exc), file=sys.stderr)
        report['configuration_exit_status'] = report.get('exit_status')
        report.update(exit_status=1, stage='report-write')
        report['errors'].append(type(exc).__name__ + ': ' + str(exc))
        report['recovery'] = ['Use --report with a new writable JSON path outside font inputs/cache, then rerun.']
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(output, end='')
    return report['exit_status']


if __name__ == '__main__':
    sys.exit(main())
