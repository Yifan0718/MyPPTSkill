"""Build an existing TeX project into fresh, hashed PDF and page evidence.

Exit 0 means build/render completion only. The report leaves visual review
pending. Managed font projects prepare their runtime font configuration first.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

from report_io import emit_report
from run_bounded import stop_owned_tree


class BuildFailure(Exception):
    def __init__(self, reason, recovery, code=3):
        super().__init__(reason)
        self.recovery, self.code = recovery, code


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def snapshot(root, excluded):
    """Conservatively cover the project, including assets not found by .fls."""
    found = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name != '.git'
                   and not (Path(directory) / name).resolve().is_relative_to(excluded)]
        for name in files:
            path = Path(directory) / name
            if not path.resolve().is_relative_to(excluded):
                found[str(path.resolve())] = digest(path)
    return found


def changed(before, after):
    return sorted(key for key in before.keys() | after.keys()
                  if before.get(key) != after.get(key))


def locate(name, explicit=None):
    candidate = str(explicit) if explicit else name
    found = shutil.which(candidate)
    if found:
        return str(Path(found).resolve())
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())
    return None


def run_stage(command, cwd, env, timeout, log, record, stage):
    """File-backed output cannot wait forever on a descendant's inherited pipe."""
    entry = {'stage': stage, 'command': list(map(str, command)), 'cwd': str(cwd),
             'log_path': str(log), 'timeout_seconds': timeout}
    record['stages'].append(entry)
    started = time.monotonic()
    child = None
    try:
        with Path(log).open('wb') as output:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                     if os.name == 'nt' else 0,
                                     start_new_session=os.name != 'nt')
            entry['pid'] = child.pid
            try:
                entry['returncode'] = child.wait(timeout=timeout)
                entry['status'] = 'finished'
            except subprocess.TimeoutExpired:
                entry['status'] = 'timed_out'
                try:
                    stop_owned_tree(child)
                except (OSError, subprocess.TimeoutExpired) as error:
                    entry['cleanup_error'] = str(error)
                entry['returncode'] = child.poll()
                raise BuildFailure('task_tool_timeout',
                                   'Inspect this stage log and partial outputs; retry in a fresh run '
                                   'with a suitable --timeout. Only this invocation tree is targeted.', 124)
            except KeyboardInterrupt:
                entry['status'] = 'cancelled'
                stop_owned_tree(child)
                entry['returncode'] = child.poll()
                raise
    except OSError as error:
        entry.update(status='launch_failed', error=str(error), returncode=None)
        raise BuildFailure('executable_launch_failed',
                           'Check the executable path, runtime dependencies and stage log: ' + str(error))
    finally:
        entry['duration_seconds'] = round(time.monotonic() - started, 3)
    return entry['returncode']


def warning_findings(log):
    rules = [('missing_character', r'Missing character:'),
             ('font_substitution', r'Font shape .*undefined|defaults substituted|font.*substitut'),
             ('overfull_box', r'Overfull \\[hv]box'),
             ('underfull_box', r'Underfull \\[hv]box'),
             ('references_or_rerun', r'undefined references|Reference .*undefined|Citation .*undefined|Label\(s\) may have changed|\brerun\s+(?:to\s+get|(?:La|Xe|Lua|pdf)?TeX|Biber|BibTeX|to\s+resolve|to\s+ensure)|(?:please|must|should|need\s+to)\s+rerun\b'),
             ('other_warning', r'Warning:')]
    findings = []
    if not log.is_file():
        return findings
    lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
    for number, line in enumerate(lines, 1):
        for category, pattern in rules:
            if re.search(pattern, line, re.IGNORECASE):
                location = re.search(r'(?:input line|at lines?)\s+(\d+)(?:--(\d+))?', line)
                findings.append({'category': category, 'message': line.strip(),
                                 'log_path': str(log), 'log_line': number,
                                 'source_line_hint': int(location.group(1)) if location else None})
                break
    return findings


def read_dependencies(fls, cwd, output_root):
    dependencies = set()
    if fls.is_file():
        for line in fls.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('PWD '):
                cwd = Path(line[4:].strip().strip('"')).resolve()
            if line.startswith('INPUT '):
                path = Path(line[6:].strip().strip('"'))
                path = (cwd / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_dir() and not path.is_relative_to(output_root):
                    dependencies.add(path)
    return dependencies


def inspect_pdf(path, expected_ratio, tolerance):
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF cannot be verified.')
    image_refs = set()
    def resolve_image_references(value):
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in image_refs:
                return
            image_refs.add(key)
            value = value.get_object()
            if value is None:
                raise ValueError('Unresolvable image resource reference: ' + str(key))
        if isinstance(value, DictionaryObject):
            for child in value.values():
                resolve_image_references(child)
        elif isinstance(value, ArrayObject):
            for child in value:
                resolve_image_references(child)

    def inspect_object(obj):
        if obj is None:
            raise ValueError('Unresolvable PDF object')
        if isinstance(obj, DictionaryObject) and obj.get('/Subtype') == '/Image':
            if not isinstance(obj, StreamObject) or not isinstance(obj._data, bytes) or not obj._data:
                raise ValueError('Image XObject lacks an encoded stream.')
            if not all(math.isfinite(float(obj[key])) and float(obj[key]) > 0 for key in ('/Width', '/Height')):
                raise ValueError('Image XObject has invalid dimensions.')
            resolve_image_references(obj)
            # Full-sized image/SMask decoding belongs to the actual renderer.
            # Do not relax pypdf's decompression limits for structure inspection.
        elif hasattr(obj, 'get_data'):
            obj.get_data()

    # Parse structure and non-image streams. Preserve encoded images for the
    # subsequent physical-page render and pixel-level visual review.
    for generation, offsets in reader.xref.items():
        for identifier in offsets:
            if identifier:
                obj = reader.get_object(IndirectObject(identifier, generation, reader))
                inspect_object(obj)
    for identifier in reader.xref_objStm:
        inspect_object(reader.get_object(IndirectObject(identifier, 0, reader)))
    pages, findings = [], []
    for number, page in enumerate(reader.pages, 1):
        box = page.mediabox
        crop = page.cropbox
        width, height = float(box.width), float(box.height)
        crop_width, crop_height = float(crop.width), float(crop.height)
        rotation = int(page.rotation) % 360
        user_unit = float(page.get('/UserUnit', 1))
        if rotation in (90, 270):
            crop_width, crop_height = crop_height, crop_width
        if not all(math.isfinite(v) and v > 0 for v in (width, height, crop_width, crop_height, user_unit)):
            raise ValueError('Page has invalid dimensions: ' + str(number))
        content = page.get_contents()
        if content is not None:
            content.get_data()
        # Resolve page resources as well as the page tree/content streams.
        if page.get('/Resources') is not None:
            page['/Resources'].get_object()
        ratio = crop_width / crop_height
        pages.append({'page': number, 'width_pt': width * user_unit,
                      'height_pt': height * user_unit, 'rotation': rotation,
                      'display_width_pt': crop_width * user_unit,
                      'display_height_pt': crop_height * user_unit, 'aspect_ratio': ratio})
        if abs(ratio - expected_ratio) > tolerance:
            findings.append({'category': 'page_geometry', 'page': number, 'actual_ratio': ratio,
                             'expected_ratio': expected_ratio,
                             'message': 'Inspect page geometry, cropping, notes and handout settings.'})
    if not pages:
        raise ValueError('PDF contains no physical pages.')
    return pages, findings


def parse_ratio(text):
    try:
        parts = text.split(':')
        result = float(parts[0]) / float(parts[1]) if len(parts) == 2 else float(text)
        if not math.isfinite(result) or result <= 0:
            raise ValueError()
        return result
    except (ValueError, ZeroDivisionError):
        raise argparse.ArgumentTypeError('Use a positive ratio such as 16:9 or 1.77778.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'schema': 'beamer-build/v1', 'status': 'failed', 'stage': 'arguments',
                          'reason': message, 'recovery': 'Run build_beamer.py --help and correct the arguments.'}), file=sys.stderr)
        raise SystemExit(2)


def parser():
    result = Parser(description=__doc__)
    result.add_argument('source', type=Path, help='Existing main .tex file; relative inputs resolve from its directory.')
    result.add_argument('--output-dir', required=True, type=Path, help='Parent for a new isolated run-<UUID> directory each time.')
    result.add_argument('--source-root', type=Path, help='Project tree to hash before/after; defaults to the main file directory.')
    result.add_argument('--engine', choices=['auto', 'latexmk', 'xelatex', 'lualatex', 'pdflatex'], default='auto')
    result.add_argument('--executable', type=Path, help='Explicit executable for --engine (requires a concrete engine).')
    result.add_argument('--latexmk-engine', choices=['auto', 'xelatex', 'lualatex', 'pdflatex'], default='auto')
    result.add_argument('--latexmk-rc', type=Path, help='Explicit trusted rc file; default disables automatic rc loading.')
    result.add_argument('--pdftoppm', type=Path, help='Explicit existing Poppler pdftoppm executable.')
    result.add_argument('--fontconfig-file', type=Path, help='Set FONTCONFIG_FILE only for spawned tools; hash this input.')
    result.add_argument('--configure-fonts', action='store_true', help='Prepare the exact managed font bundle; automatic for MyPPTSkill font-entry projects.')
    result.add_argument('--fonts-offline', action='store_true', help='Use bundled/local/cached exact fonts without downloads.')
    result.add_argument('--font-cache-dir', type=Path, help='Use a writable managed font cache; forwarded to font preparation.')
    result.add_argument('--timeout', type=float, default=300, help='Positive per-command timeout in seconds (default: 300).')
    result.add_argument('--max-passes', type=int, default=5, help='Direct engines: 2..20 passes, stopping when auxiliary hashes stabilize.')
    result.add_argument('--dpi', type=int, default=144, help='Page render resolution (36..600; default: 144).')
    result.add_argument('--expected-ratio', type=parse_ratio, default=16 / 9, help='Geometry finding target, default 16:9; does not block.')
    result.add_argument('--ratio-tolerance', type=float, default=0.01, help='Absolute ratio tolerance (default: 0.01).')
    return result


def build(args):
    record = {'schema': 'beamer-build/v1', 'run_id': uuid.uuid4().hex,
              'status': 'running', 'visual_review': 'pending', 'signed_off': False,
              'started_at': datetime.now(timezone.utc).isoformat(), 'stages': [], 'findings': []}
    run_dir = None
    phase = 'preflight'
    code = 3
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise BuildFailure('invalid_timeout', 'Provide a positive finite --timeout.')
        if not 2 <= args.max_passes <= 20 or not 36 <= args.dpi <= 600:
            raise BuildFailure('invalid_numeric_option', 'Use --max-passes 2..20 and --dpi 36..600.')
        if not math.isfinite(args.ratio_tolerance) or args.ratio_tolerance < 0:
            raise BuildFailure('invalid_ratio_tolerance', 'Provide a finite nonnegative --ratio-tolerance.')
        source, output_root = args.source.resolve(), args.output_dir.resolve()
        root = args.source_root.resolve() if args.source_root else source.parent
        if not source.is_file() or source.suffix.lower() != '.tex':
            raise BuildFailure('missing_tex_input', 'Supply the existing main .tex file; recover missing project files before compiling.')
        if not root.is_dir() or not source.is_relative_to(root):
            raise BuildFailure('invalid_source_root', 'Choose a --source-root directory containing the main TeX file and local dependencies.')
        if root.is_relative_to(output_root):
            raise BuildFailure('output_contains_inputs', 'Choose an output directory separate from or nested inside the source project, never its ancestor.')
        if args.executable and args.engine == 'auto':
            raise BuildFailure('ambiguous_executable', 'Set --engine to the kind of executable supplied with --executable.')
        extras = {}
        for name in ('fontconfig_file', 'latexmk_rc'):
            path = getattr(args, name)
            if path:
                path = path.resolve()
                if not path.is_file() or path.is_relative_to(output_root):
                    raise BuildFailure('missing_or_output_scoped_' + name, 'Provide an existing configuration file outside --output-dir.')
                extras[str(path)] = digest(path)
        run_dir = output_root / ('run-' + record['run_id'])
        run_dir.mkdir(parents=True, exist_ok=False)
        record.update(source_path=str(source), source_root=str(root), output_dir=str(run_dir),
                      report_path=str(run_dir / 'build-report.json'), dpi=args.dpi,
                      expected_ratio=args.expected_ratio, ratio_tolerance=args.ratio_tolerance)
        env = os.environ.copy()
        if args.fontconfig_file:
            env['FONTCONFIG_FILE'] = str(args.fontconfig_file.resolve())
        # An explicit engine directory supplies its companion converters without
        # assuming the user's global PATH contains that TeX installation.
        if args.executable:
            env['PATH'] = str(args.executable.resolve().parent) + os.pathsep + env.get('PATH', '')
        available = {name: shutil.which(name, path=env.get('PATH'))
                     for name in ('latexmk', 'xelatex', 'lualatex', 'pdflatex')}
        record['available_tools'] = available
        tex_engine = args.latexmk_engine
        if tex_engine == 'auto':
            tex_engine = next((name for name in ('xelatex', 'lualatex', 'pdflatex') if available[name]), None)
        engine = args.engine
        if engine == 'auto':
            engine = 'latexmk' if available['latexmk'] and tex_engine else tex_engine
        executable = locate(engine, args.executable) if engine else None
        if not executable:
            raise BuildFailure('missing_tex_executor',
                               'Use an existing latexmk/XeLaTeX/LuaLaTeX/pdfLaTeX via PATH or --engine and --executable. '
                               'If no TeX runtime exists, continue source editing and provide the project to an existing TeX environment; no runtime is installed.')
        if engine == 'latexmk' and (not tex_engine or not available.get(tex_engine)):
            raise BuildFailure('missing_latexmk_engine', 'Expose the requested TeX engine beside latexmk or on PATH, or select another existing direct --engine.')
        if args.latexmk_rc and engine != 'latexmk':
            raise BuildFailure('rc_requires_latexmk', 'Use --engine latexmk with --latexmk-rc.')
        renderer = locate('pdftoppm', args.pdftoppm)
        if not renderer:
            raise BuildFailure('missing_renderer',
                               'Supply existing Poppler with --pdftoppm or PATH. Fallback: render the same PDF with MuPDF/PyMuPDF '
                               'in a separate fresh directory and verify every physical page with hashes; this run remains incomplete.')
        try:
            import pypdf
            import PIL
            from PIL import Image
        except ImportError as error:
            raise BuildFailure('missing_python_dependency', 'Use a Python runtime containing pypdf and Pillow: ' + str(error))
        record.update(engine=engine, tex_engine=tex_engine if engine == 'latexmk' else engine,
                      executable=executable, renderer=renderer,
                      fontconfig_file=env.get('FONTCONFIG_FILE'),
                      python_version=sys.version, python_executable=sys.executable,
                      library_versions={'pypdf': pypdf.__version__, 'Pillow': PIL.__version__})
        # An inherited FONTCONFIG_FILE is an input too, when it names a file.
        if env.get('FONTCONFIG_FILE') and Path(env['FONTCONFIG_FILE']).is_file():
            path = Path(env['FONTCONFIG_FILE']).resolve()
            extras[str(path)] = digest(path)
        managed = getattr(args, 'configure_fonts', False) or any(
            'MyPPTSkill managed-font-entry' in p.read_text(encoding='utf-8-sig', errors='replace')
            for p in root.rglob('*.tex') if not p.resolve().is_relative_to(output_root))
        if managed:
            phase = 'font-preparation'
            from setup_fonts import setup_fonts, DEFAULT_MANIFEST
            fonts = setup_fonts(project_dir=source.parent, offline=getattr(args, 'fonts_offline', False),
                                cache_dir=getattr(args, 'font_cache_dir', None))
            font_report = run_dir / 'font-setup.json'
            font_report.write_text(json.dumps(fonts, ensure_ascii=False, indent=2), encoding='utf-8')
            record['font_setup'] = {'path': str(font_report), 'sha256': digest(font_report),
                                    'exit_status': fonts.get('exit_status'),
                                    'cache_ready': fonts.get('cache_ready'), 'os_available': fonts.get('os_available'),
                                    'errors': fonts.get('errors', []), 'recovery': fonts.get('recovery', [])}
            if type(fonts.get('exit_status')) is not int or fonts.get('exit_status') not in (0, 2) or fonts.get('cache_ready') is not True:
                raise BuildFailure('managed_fonts_unavailable',
                    'Inspect font-setup.json and its recovery list. Restore the exact resources/connectivity; for cache conflicts use --font-cache-dir with a new writable directory. Retry once after repairing the cause; continue independent content work with the original content plan.')
            if not isinstance(fonts.get('font_files'), list) or not fonts['font_files']:
                raise BuildFailure('managed_font_evidence_missing', 'Restore the complete font preparation report and rebuild; no compiler was started.')
            extras[str(DEFAULT_MANIFEST.resolve())] = digest(DEFAULT_MANIFEST)
            for font in fonts.get('font_files', []):
                path = Path(font['path']).resolve()
                if not path.is_file() or digest(path) != font['sha256']:
                    raise BuildFailure('managed_font_hash_mismatch', 'Restore the exact managed font file and rebuild.')
                extras[str(path)] = font['sha256']
        before = snapshot(root, output_root)
        before.update(extras)
        record['input_hashes_before'] = before
        started_ns = time.time_ns()
        phase = 'typeset'
        common = ['-interaction=nonstopmode', '-halt-on-error', '-file-line-error', '-recorder', '-no-shell-escape']
        if engine == 'latexmk':
            command = [executable, '-norc']
            if args.latexmk_rc:
                command += ['-r', str(args.latexmk_rc.resolve())]
            command += [{'xelatex': '-xelatex', 'lualatex': '-lualatex', 'pdflatex': '-pdf'}[tex_engine]]
            command += common + ['-jobname=deck', '-outdir=' + str(run_dir), str(source)]
            result = run_stage(command, source.parent, env, args.timeout, run_dir / 'typeset.log', record, phase)
            if result:
                raise BuildFailure('tex_process_failed', 'Inspect typeset.log and deck.log, repair the first TeX error, then rerun into a fresh directory.', result)
        else:
            previous = None
            record['auxiliary_converged'] = False
            for index in range(1, args.max_passes + 1):
                command = [executable] + common + ['-jobname=deck', '-output-directory=' + str(run_dir), str(source)]
                result = run_stage(command, source.parent, env, args.timeout,
                                   run_dir / ('typeset-%02d.log' % index), record,
                                   'typeset' if index == 1 else 'auxiliary-rerun')
                if result:
                    raise BuildFailure('tex_process_failed', 'Inspect this pass log and deck.log, repair the first TeX error, then rerun.', result)
                auxiliary = {path.name: digest(path) for path in run_dir.iterdir()
                             if path.name.endswith(('.aux', '.toc', '.nav', '.snm', '.out', '.bcf', '.run.xml'))}
                if auxiliary == previous:
                    record['auxiliary_converged'] = True
                    break
                previous = auxiliary
            if not record['auxiliary_converged']:
                record['findings'].append({'category': 'auxiliary_convergence',
                                          'message': 'Auxiliary hashes did not stabilize; inspect references and use latexmk or increase --max-passes.'})
        record['warnings'] = warning_findings(run_dir / 'deck.log')
        fls = run_dir / 'deck.fls'
        dependencies = read_dependencies(fls, source.parent, output_root)
        if not fls.is_file():
            record['findings'].append({'category': 'dependency_coverage',
                                      'message': 'Recorder .fls is missing; only project/configuration inputs have before/after hashes. Inspect external dependencies.'})
        record['dependency_coverage'] = {
            'project_tree': 'Full before/after SHA-256 snapshots excluding .git and output-dir.',
            'recorder_present': fls.is_file(), 'recorder_path': str(fls),
            'external_inputs': 'Recorded after compilation; mtime/ctime checked against start, then SHA-256 checked after rendering.',
            'limitation': 'First-seen external dependencies have no pre-build hash; preserved timestamps, unrecorded OS fonts and concurrent edits reverted before checks are not fully covered.'}
        missing = [str(path) for path in dependencies if not path.is_file()]
        if missing:
            record['changed_inputs'] = missing
            raise BuildFailure('recorder_input_missing', 'Restore the recorder-listed inputs that vanished during compilation, freeze the project, and rebuild.')
        dep_hashes = {str(path): digest(path) for path in dependencies}
        record['dependency_hashes'] = dep_hashes
        suspect = [str(path) for path in dependencies if str(path) not in before
                   and max(path.stat().st_mtime_ns, path.stat().st_ctime_ns) >= started_ns]
        after_compile = snapshot(root, output_root)
        after_compile.update({path: digest(path) if Path(path).is_file() else None for path in extras})
        modifications = changed(before, after_compile)
        if modifications or suspect:
            record['changed_inputs'] = sorted(set(modifications + suspect))
            raise BuildFailure('inputs_changed_during_build', 'Freeze the listed source/dependency inputs and rebuild in a new run directory.')
        phase = 'pdf-open'
        pdf = run_dir / 'deck.pdf'
        if not pdf.is_file() or not pdf.stat().st_size:
            raise BuildFailure('fresh_pdf_missing', 'The current invocation produced no PDF. Inspect TeX/converter logs; previous PDFs are not used.')
        try:
            pages, geometry = inspect_pdf(pdf, args.expected_ratio, args.ratio_tolerance)
        except Exception as error:
            raise BuildFailure('pdf_invalid', 'Repair the PDF build/conversion and rebuild. Parser detail: ' + str(error))
        phase = 'pdf-metadata-preparation'
        try:
            from pdf_generator_metadata import prepare_generator_metadata
            record['metadata_preparation'] = prepare_generator_metadata(pdf, owned_run_dir=run_dir)
        except Exception as error:
            raise BuildFailure('pdf_metadata_preparation_failed',
                               'Inspect the preserved compiled PDF and metadata; repair the metadata preparation before delivery. Detail: ' + str(error))
        pdf_hash = digest(pdf)
        record.update(pdf_path=str(pdf), pdf_sha256=pdf_hash, physical_page_count=len(pages), pages=pages)
        record['findings'].extend(geometry)
        phase = 'render'
        render_dir = run_dir / 'pages'
        render_dir.mkdir()
        record['renders'] = []
        for page in pages:
            number = page['page']
            prefix = render_dir / ('page-%04d' % number)
            command = [renderer, '-f', str(number), '-l', str(number), '-singlefile', '-cropbox', '-r', str(args.dpi), '-png', str(pdf), str(prefix)]
            result = run_stage(command, source.parent, env, args.timeout,
                               run_dir / ('render-%04d.log' % number), record, 'render-page-' + str(number))
            if result:
                raise BuildFailure('render_process_failed',
                                   'Inspect the page render log; retry existing Poppler, or render this exact PDF with MuPDF/PyMuPDF '
                                   'into a separate fresh directory and verify all physical pages and hashes.', result)
            png = prefix.with_suffix('.png')
            try:
                with Image.open(png) as image:
                    image.verify()
                with Image.open(png) as image:
                    image.load()
                    size = image.size
                if min(size) <= 0:
                    raise ValueError('Empty page image.')
                expected_size = (page['display_width_pt'] * args.dpi / 72,
                                 page['display_height_pt'] * args.dpi / 72)
                # Poppler uses the MediaBox unless explicitly asked for CropBox.
                # Match the inspected display box when rendering cropped PDFs.
                if any(abs(actual - expected) > 2 for actual, expected in zip(size, expected_size)):
                    raise ValueError('Page raster dimensions do not match the PDF box and requested DPI.')
            except Exception as error:
                raise BuildFailure('render_page_missing_or_invalid', 'Rerender physical page %d; inspect its log or use independent MuPDF/PyMuPDF. Detail: %s' % (number, error))
            record['renders'].append({'page': number, 'path': str(png), 'sha256': digest(png),
                                      'width_px': size[0], 'height_px': size[1], 'pdf_sha256': pdf_hash})
        phase = 'layout-audit'
        from audit_beamer_layout import audit_pdf
        layout = audit_pdf(pdf)
        if layout['pdf']['sha256'] != pdf_hash or layout['physical_page_count'] != len(pages):
            raise BuildFailure('layout_pdf_changed', 'Freeze the PDF and rebuild the PDF, measurements and renders together.')
        layout_path = run_dir / 'layout-audit.json'
        if emit_report(layout_path, layout, inputs=[pdf], frozen_dirs=[render_dir]):
            raise BuildFailure('layout_report_write_failed', 'Preserve the current PDF/renders and retry with a writable output directory.')
        record['layout_audit'] = {'path': str(layout_path), 'sha256': digest(layout_path)}
        record['findings'].extend(layout['findings'])
        phase = 'input-stability'
        after = snapshot(root, output_root)
        after.update({path: digest(path) if Path(path).is_file() else None for path in extras})
        record['input_hashes_after'] = after
        dep_after = {path: digest(path) if Path(path).is_file() else None for path in dep_hashes}
        modifications = sorted(set(changed(before, after) + changed(dep_hashes, dep_after)))
        if modifications or digest(pdf) != pdf_hash:
            record['changed_inputs'] = modifications
            raise BuildFailure('inputs_or_pdf_changed', 'Freeze sources, dependencies and PDF, then rebuild and rerender together in a fresh run.')
        record.update(status='pending_visual_review', next_step='Inspect every physical page and relevant close-ups; record review against these PDF/image hashes. Build completion is not visual sign-off.')
        code = 0
    except BuildFailure as error:
        code = error.code
        record.update(status='failed', stage=phase, reason=str(error), recovery=error.recovery)
    except KeyboardInterrupt:
        code = 130
        record.update(status='cancelled', stage=phase, reason='task_cancelled', recovery='Partial evidence is retained; resume when requested.')
    except Exception as error:
        code = 3
        record.update(status='failed', stage=phase, reason=type(error).__name__ + ': ' + str(error),
                      recovery='Inspect the retained stage logs and paths; fix the input/environment and retry in a new run directory.')
    record.update(exit_code=code, finished_at=datetime.now(timezone.utc).isoformat())
    if run_dir:
        report_code = emit_report(run_dir / 'build-report.json', record)
        if report_code:
            code = report_code
            record.update(exit_code=code, status='failed', reason='report_write_failed')
    print(json.dumps(record, ensure_ascii=True, allow_nan=False))
    return code


def main(argv=None):
    return build(parser().parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
