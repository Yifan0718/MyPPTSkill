"""Beamer build contract tests using real child processes and synthetic artifacts."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch

import build_beamer as beamer


FAKE = r'''
import json, os, sys, time
from pathlib import Path
from pypdf import PdfWriter, PdfReader
from PIL import Image
role, config_path = sys.argv[1:3]
args = sys.argv[3:]
config = json.loads(Path(config_path).read_text())
if role == 'tex':
    output = Path(next(x.split('=', 1)[1] for x in args if x.startswith(('-output-directory=', '-outdir='))))
    source = Path(args[-1])
    if config.get('sleep'):
        time.sleep(config['sleep'])
    if config.get('exit'):
        print('Intentional compiler failure', flush=True)
        sys.exit(config['exit'])
    if config.get('change_source'):
        source.write_text(source.read_text() + '\n% changed')
    if config.get('delete_source'):
        source.unlink()
    if config.get('corrupt'):
        (output/'deck.pdf').write_bytes(b'%PDF-1.7\nnot a valid pdf')
    elif not config.get('no_pdf'):
        writer = PdfWriter()
        for index in range(config.get('pages', 1)):
            writer.add_blank_page(config.get('width', 160), config.get('height', 90))
        with (output/'deck.pdf').open('wb') as f:
            writer.write(f)
    (output/'deck.aux').write_text(str(time.time_ns()) if config.get('unstable_aux') else 'stable auxiliary')
    (output/'deck.log').write_text(config.get('warnings', ''))
    deps = [str(source)] + config.get('deps', [])
    (output/'deck.fls').write_text('\n'.join('INPUT ' + x for x in deps))
    (output/'font-env.txt').write_text(os.environ.get('FONTCONFIG_FILE', ''))
    if config.get('change_dependency'):
        Path(config['change_dependency']).write_text('changed external')
else:
    page = int(args[args.index('-f') + 1])
    if config.get('render_exit'):
        sys.exit(config['render_exit'])
    if page != config.get('missing_page'):
        pdf = PdfReader(args[-2])
        box = pdf.pages[page-1].cropbox
        dpi = int(args[args.index('-r') + 1])
        size = (round(float(box.width)*dpi/72), round(float(box.height)*dpi/72))
        Image.new('RGB', size, 'white').save(args[-1] + '.png')
    if config.get('change_while_rendering'):
        path = Path(config['change_while_rendering'])
        path.write_text(path.read_text() + '\n% rendered mutation')
'''


class BeamerBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='beamer-build-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.source = self.project / 'main.tex'
        self.source.write_text(r'\documentclass[aspectratio=169]{beamer}\begin{document}\begin{frame}A\pause B\end{frame}\end{document}')
        self.output = self.base / 'build'
        self.fake = self.base / 'fake.py'
        self.fake.write_text(FAKE)
        self.config = self.base / 'config.json'
        self.config.write_text('{}')
        self.popen = subprocess.Popen

    def invoke(self, config=None, extra=None, engine='xelatex'):
        self.config.write_text(json.dumps(config or {}))
        def launch(command, **kwargs):
            role = 'tex' if any(x.startswith(('-output-directory=', '-outdir=')) for x in command) else 'render'
            return self.popen([sys.executable, str(self.fake), role, str(self.config)] + command[1:], **kwargs)
        args = [str(self.source), '--output-dir', str(self.output), '--engine', engine,
                '--pdftoppm', sys.executable]
        if engine != 'auto':
            args += ['--executable', sys.executable]
        args += extra or []
        stream = io.StringIO()
        with patch.object(beamer.subprocess, 'Popen', side_effect=launch), contextlib.redirect_stdout(stream):
            code = beamer.main(args)
        return code, json.loads(stream.getvalue())

    def test_overlay_physical_pages_are_all_rendered_pending_review(self):
        code, report = self.invoke({'pages': 3})
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'pending_visual_review')
        self.assertFalse(report['signed_off'])
        self.assertEqual(report['visual_review'], 'pending')
        self.assertEqual(report['physical_page_count'], 3)
        self.assertEqual([x['page'] for x in report['renders']], [1, 2, 3])
        self.assertEqual([x['page'] for x in report['findings']], [1, 2, 3])
        self.assertTrue(all(x['category'] in ('empty_page_candidate', 'layout_measurement_unavailable')
                            for x in report['findings']))
        layout = json.loads(Path(report['layout_audit']['path']).read_text())
        self.assertEqual(report['layout_audit']['sha256'], beamer.digest(report['layout_audit']['path']))
        self.assertEqual(layout['pdf']['sha256'], report['pdf_sha256'])
        self.assertEqual(layout['coverage']['expected_pages'], [1, 2, 3])
        self.assertTrue(report['auxiliary_converged'])
        for item in report['renders']:
            self.assertEqual(item['sha256'], beamer.digest(item['path']))
            self.assertEqual(item['pdf_sha256'], report['pdf_sha256'])
        self.assertEqual(json.loads(Path(report['report_path']).read_text()), report)

    def test_real_compiler_returncode_is_retained(self):
        code, report = self.invoke({'exit': 17})
        self.assertEqual(code, 17)
        self.assertEqual(report['stages'][0]['returncode'], 17)
        self.assertEqual(report['reason'], 'tex_process_failed')
        self.assertIn('Intentional', Path(report['stages'][0]['log_path']).read_text())

    def test_unmanaged_project_does_not_reconfigure_fonts(self):
        with patch('setup_fonts.setup_fonts') as setup:
            code, report = self.invoke()
        self.assertEqual(code,0); setup.assert_not_called()
        self.assertNotIn('font_setup',report)

    def managed_font_fixture(self):
        self.source.write_text('% MyPPTSkill managed-font-entry\n'+self.source.read_text())
        font=self.base/'exact.otf';font.write_bytes(b'exact font fixture')
        def setup(**kwargs):
            (self.project/'myppt-fonts.tex').write_text('% configured before snapshot')
            return {'cache_ready':True,'os_available':False,'exit_status':2,
                    'font_files':[{'path':str(font),'sha256':beamer.digest(font)}]}
        return font, setup

    def test_exact_cached_fonts_continue_when_os_install_unavailable(self):
        font,setup=self.managed_font_fixture()
        with patch('setup_fonts.setup_fonts',side_effect=setup) as called:
            code,report=self.invoke(extra=['--fonts-offline'])
        self.assertEqual(code,0,report)
        self.assertTrue(called.call_args.kwargs['offline'])
        self.assertEqual(report['font_setup']['exit_status'],2)
        self.assertIn(str(font),report['input_hashes_before'])
        self.assertIn(str(self.project/'myppt-fonts.tex'),report['input_hashes_before'])

    def test_font_preparation_failure_stops_typeset_with_recovery(self):
        self.source.write_text('% MyPPTSkill managed-font-entry\n'+self.source.read_text())
        with patch('setup_fonts.setup_fonts',return_value={'cache_ready':False,'exit_status':1,'errors':['hash mismatch']}):
            code,report=self.invoke()
        self.assertNotEqual(code,0)
        self.assertEqual(report['reason'],'managed_fonts_unavailable')
        self.assertEqual(report['stages'],[])
        self.assertIn('exact',report['recovery'])

    def test_cached_font_mutation_invalidates_build(self):
        font,setup=self.managed_font_fixture()
        with patch('setup_fonts.setup_fonts',side_effect=setup):
            code,report=self.invoke({'change_while_rendering':str(font)})
        self.assertNotEqual(code,0)
        self.assertIn(str(font),report.get('changed_inputs',[]))

    def test_font_cache_recovery_path_is_forwarded(self):
        font,setup=self.managed_font_fixture()
        cache=self.base/'fresh font cache'
        with patch('setup_fonts.setup_fonts',side_effect=setup) as called:
            code,report=self.invoke(extra=['--font-cache-dir',str(cache)])
        self.assertEqual(code,0,report)
        self.assertEqual(called.call_args.kwargs['cache_dir'],cache)

    def test_font_failure_details_reach_build_report(self):
        self.source.write_text('% MyPPTSkill managed-font-entry\n'+self.source.read_text())
        failure={'cache_ready':False,'exit_status':1,'errors':['download timeout'],
                 'recovery':['Restore network access then retry once.']}
        with patch('setup_fonts.setup_fonts',return_value=failure):
            code,report=self.invoke()
        self.assertNotEqual(code,0)
        self.assertEqual(report['font_setup']['exit_status'],1)
        self.assertEqual(report['font_setup']['errors'],failure['errors'])
        self.assertEqual(report['font_setup']['recovery'],failure['recovery'])
        self.assertEqual(report['stages'],[])

    def test_malformed_font_success_cannot_start_typesetting(self):
        self.source.write_text('% MyPPTSkill managed-font-entry\n'+self.source.read_text())
        for value in ({'exit_status':False,'cache_ready':True},
                      {'exit_status':0,'cache_ready':'yes'},
                      {'exit_status':0,'cache_ready':True,'font_files':[]}):
            with self.subTest(value=value),patch('setup_fonts.setup_fonts',return_value=value):
                code,report=self.invoke()
                self.assertNotEqual(code,0)
                self.assertEqual(report['stages'],[])

    def test_optional_layout_parser_failure_retains_renders_for_independent_review(self):
        import audit_beamer_layout as layout_audit
        with patch.object(layout_audit.importlib, 'import_module', side_effect=ImportError('PyMuPDF unavailable')):
            code, report = self.invoke({'pages': 2})
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'pending_visual_review')
        self.assertEqual([row['page'] for row in report['renders']], [1, 2])
        self.assertEqual([row['category'] for row in report['findings']],
                         ['layout_measurement_unavailable', 'layout_measurement_unavailable'])
        layout = json.loads(Path(report['layout_audit']['path']).read_text())
        self.assertEqual(layout['status'], 'incomplete')
        self.assertEqual(layout['coverage']['unavailable_pages'], [1, 2])
        self.assertTrue(all(row['visual_review'] == 'pending' for row in layout['pages']))

    def test_real_renderer_returncode_is_retained(self):
        code, report = self.invoke({'render_exit': 19})
        self.assertEqual(code, 19)
        self.assertEqual(report['stages'][-1]['returncode'], 19)
        self.assertEqual(report['reason'], 'render_process_failed')
        self.assertIn('MuPDF', report['recovery'])

    def test_timeout_retains_log_and_kills_owned_invocation(self):
        started = time.monotonic()
        # Keep real taskkill out of the fake executable dispatch on Windows.
        original_stop = beamer.stop_owned_tree
        def stop(child):
            with patch.object(beamer.subprocess, 'Popen', self.popen):
                original_stop(child)
        with patch.object(beamer, 'stop_owned_tree', side_effect=stop):
            code, report = self.invoke({'sleep': 30}, ['--timeout', '0.4'])
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(report['stages'][0]['status'], 'timed_out')
        self.assertIsNotNone(report['stages'][0]['returncode'])

    def test_stale_pdf_cannot_supply_success(self):
        code, prior = self.invoke()
        self.assertEqual(code, 0)
        code, report = self.invoke({'no_pdf': True})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'fresh_pdf_missing')
        self.assertNotEqual(prior['output_dir'], report['output_dir'])
        self.assertTrue(Path(prior['pdf_path']).is_file())

    def test_corrupt_pdf_fails(self):
        code, report = self.invoke({'corrupt': True})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'pdf_invalid')

    def test_image_and_soft_mask_are_not_preemptively_decompressed(self):
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import DictionaryObject, EncodedStreamObject, NameObject, NumberObject
        import pypdf.filters as filters
        writer = PdfWriter()
        page = writer.add_blank_page(160, 90)
        def image():
            stream = EncodedStreamObject()
            stream._data = zlib.compress(b'\x7f' * 4096)
            stream.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                           NameObject('/Width'): NumberObject(64), NameObject('/Height'): NumberObject(64),
                           NameObject('/BitsPerComponent'): NumberObject(8), NameObject('/ColorSpace'): NameObject('/DeviceGray'),
                           NameObject('/Filter'): NameObject('/FlateDecode')})
            return stream
        main, mask = image(), image()
        main[NameObject('/SMask')] = writer._add_object(mask)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im1'): writer._add_object(main)})})
        path = self.base / 'large-image.pdf'
        with path.open('wb') as stream:
            writer.write(stream)
        with patch.object(filters, 'ZLIB_MAX_OUTPUT_LENGTH', 64):
            with self.assertRaises(Exception):
                PdfReader(path).pages[0]['/Resources']['/XObject']['/Im1'].get_data()
            pages, _ = beamer.inspect_pdf(path, 16 / 9, .01)
        self.assertEqual(len(pages), 1)

    def test_bad_page_content_and_missing_eof_are_still_rejected(self):
        from pypdf import PdfWriter
        from pypdf.generic import EncodedStreamObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(160, 90)
        content = EncodedStreamObject()
        content._data = b'broken page content'
        content[NameObject('/Filter')] = NameObject('/UnsupportedContentFilter')
        page[NameObject('/Contents')] = writer._add_object(content)
        path = self.base / 'bad-content.pdf'
        with path.open('wb') as stream:
            writer.write(stream)
        with self.assertRaises(Exception):
            beamer.inspect_pdf(path, 16 / 9, .01)
        valid = PdfWriter()
        valid.add_blank_page(160, 90)
        with path.open('wb') as stream:
            valid.write(stream)
        path.write_bytes(path.read_bytes().replace(b'%%EOF', b''))
        with self.assertRaises(Exception):
            beamer.inspect_pdf(path, 16 / 9, .01)

    def test_input_mutation_during_compile_fails(self):
        code, report = self.invoke({'change_source': True})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'inputs_changed_during_build')
        self.assertIn(str(self.source.resolve()), report['changed_inputs'])

    def test_input_mutation_during_render_fails(self):
        code, report = self.invoke({'change_while_rendering': str(self.source)})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'inputs_or_pdf_changed')

    def test_external_recorder_dependency_is_hashed_and_change_detected(self):
        dependency = self.base / 'external.tex'
        dependency.write_text('original')
        code, report = self.invoke({'deps': [str(dependency)]})
        self.assertEqual(code, 0)
        self.assertEqual(report['dependency_hashes'][str(dependency.resolve())], beamer.digest(dependency))
        code, report = self.invoke({'deps': [str(dependency)], 'change_dependency': str(dependency)})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'inputs_changed_during_build')

    def test_geometry_and_warnings_are_findings_not_build_gates(self):
        warnings = 'Overfull \\hbox (5pt too wide) at lines 5--6\nUnderfull \\vbox\nMissing character: x\nLaTeX Font Warning: Font shape foo undefined\nLaTeX Warning: There were undefined references.'
        code, report = self.invoke({'width': 120, 'height': 90, 'warnings': warnings})
        self.assertEqual(code, 0)
        self.assertEqual(report['findings'][0]['category'], 'page_geometry')
        self.assertEqual(report['physical_page_count'], 1)
        self.assertEqual({item['category'] for item in report['warnings']},
                         {'overfull_box', 'underfull_box', 'missing_character', 'font_substitution', 'references_or_rerun'})
        self.assertEqual(report['warnings'][0]['source_line_hint'], 5)

    def test_old_renders_do_not_fill_missing_new_page(self):
        code, prior = self.invoke({'pages': 3})
        self.assertEqual(code, 0)
        code, report = self.invoke({'pages': 3, 'missing_page': 2})
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'render_page_missing_or_invalid')
        self.assertEqual(len(report['renders']), 1)
        self.assertTrue(Path(prior['renders'][1]['path']).is_file())

    def test_explicit_fontconfig_is_scoped_and_hashed(self):
        fontconfig = self.base / 'fonts.conf'
        fontconfig.write_text('<fontconfig/>')
        old = os.environ.get('FONTCONFIG_FILE')
        code, report = self.invoke(extra=['--fontconfig-file', str(fontconfig)])
        self.assertEqual(code, 0)
        self.assertEqual((Path(report['output_dir'])/'font-env.txt').read_text(), str(fontconfig.resolve()))
        self.assertEqual(report['input_hashes_before'][str(fontconfig.resolve())], beamer.digest(fontconfig))
        self.assertEqual(os.environ.get('FONTCONFIG_FILE'), old)

    def test_missing_executor_and_renderer_have_structured_recovery(self):
        stream = io.StringIO()
        with patch.object(beamer.shutil, 'which', return_value=None), contextlib.redirect_stdout(stream):
            code = beamer.main([str(self.source), '--output-dir', str(self.output)])
        report = json.loads(stream.getvalue())
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'missing_tex_executor')
        self.assertIn('existing', report['recovery'])
        with patch.object(beamer, 'locate', side_effect=lambda name, explicit=None: sys.executable if name == 'xelatex' else None):
            code, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'missing_renderer')

    def test_missing_input_has_structured_diagnostic(self):
        self.source.unlink()
        code, report = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertEqual(report['reason'], 'missing_tex_input')

    def test_auto_prefers_latexmk_when_both_tools_exist(self):
        with patch.object(beamer.shutil, 'which', return_value=sys.executable):
            code, report = self.invoke(engine='auto')
        self.assertEqual(code, 0)
        self.assertEqual(report['engine'], 'latexmk')
        self.assertEqual(report['tex_engine'], 'xelatex')
        self.assertIn('-norc', report['stages'][0]['command'])
        self.assertIn('-xelatex', report['stages'][0]['command'])

    def test_auto_falls_back_to_available_direct_lualatex(self):
        with patch.object(beamer.shutil, 'which', side_effect=lambda name, **kw: None if name in ('latexmk', 'xelatex') else sys.executable):
            code, report = self.invoke(engine='auto')
        self.assertEqual(code, 0)
        self.assertEqual(report['engine'], 'lualatex')

    def test_direct_pass_limit_records_convergence_finding(self):
        code, report = self.invoke({'unstable_aux': True}, ['--max-passes', '2'])
        self.assertEqual(code, 0)
        self.assertFalse(report['auxiliary_converged'])
        self.assertIn('auxiliary_convergence', [item['category'] for item in report['findings']])

    def test_recorder_tracks_its_pwd_and_retains_missing_inputs(self):
        directory = self.base / 'external-dir'
        directory.mkdir()
        existing = directory / 'part.tex'
        existing.write_text('content')
        missing = directory / 'vanished.tex'
        fls = self.base / 'sample.fls'
        fls.write_text('PWD ' + str(directory) + '\nINPUT part.tex\nINPUT vanished.tex\n')
        self.assertEqual(beamer.read_dependencies(fls, self.project, self.output),
                         {existing.resolve(), missing.resolve()})

    def test_rerun_package_metadata_is_not_a_warning(self):
        log = self.base / 'metadata.log'
        log.write_text('\n'.join([
            '(C:/texlive/tex/latex/rerunfilecheck/rerunfilecheck.sty',
            'Package: rerunfilecheck 2025/06/21 v1.11 Rerun checks for auxiliary files',
            'Package rerunfilecheck Info: File `deck.out` has not changed.',
            '(rerunfilecheck) Checksum: D41D8CD98F00B204E9800998ECF8427E;0.',
            'Package rerunfilecheck Info: Checksums for `deck.out`:',
            'LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.',
            '(rerunfilecheck) Rerun to get outlines right',
            'Package rerunfilecheck Warning: File `deck.out` has changed.',
            "Package biblatex Warning: Please (re)run Biber on the file:",
            'Overfull \\hbox (4pt too wide) at lines 12--13',
        ]))
        findings = beamer.warning_findings(log)
        self.assertEqual(len(findings), 5)
        self.assertEqual([row['log_line'] for row in findings], [6, 7, 8, 9, 10])
        self.assertEqual(findings[-1]['category'], 'overfull_box')

    def test_timeout_stops_descendant_but_preserves_unrelated_process(self):
        ready, survived = self.base / 'child-ready', self.base / 'child-survived'
        child_code = ('from pathlib import Path;import time;'
                      'Path(%r).write_text("ready");time.sleep(2);Path(%r).write_text("alive")'
                      % (str(ready), str(survived)))
        parent_code = ('import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",%r]);time.sleep(30)'
                       % child_code)
        unrelated = self.popen([sys.executable, '-c', 'import time;time.sleep(30)'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            record = {'stages': []}
            with self.assertRaises(beamer.BuildFailure) as caught:
                beamer.run_stage([sys.executable, '-c', parent_code], self.base, os.environ.copy(),
                                 0.8, self.base / 'tree.log', record, 'tree-timeout')
            self.assertEqual(caught.exception.code, 124)
            self.assertTrue(ready.is_file(), 'Descendant must have actually started before timeout.')
            time.sleep(2.1)
            self.assertFalse(survived.exists(), 'Task-owned descendant outlived tree termination.')
            self.assertIsNone(unrelated.poll(), 'Unrelated process must remain alive.')
        finally:
            unrelated.kill()
            unrelated.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
