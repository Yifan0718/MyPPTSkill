"""Synthetic evidence contract fixtures, not human visual sign-off records."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pypdf import PdfWriter
import verify_beamer_review as gate
import skill_state


class BeamerReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='beamer-review-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'main.tex'
        self.source.write_text('synthetic test source')
        self.lock_path=self.root/'skill-lock.json'
        skill_state.snapshot(self.lock_path,Path(gate.__file__).resolve().parent.parent)
        self.build_path, self.build = self.make_build('current')
        self.review_path = self.root / 'review.json'
        self.review = self.make_review(self.build_path, self.build)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf8')
        return path

    def link(self, path):
        return {'path': str(path.resolve()), 'sha256': gate.sha(path)}

    def make_build(self, name, colors=('white', 'gray'), source=None):
        directory = self.root / name
        directory.mkdir()
        source = source or self.source
        pdf = directory / 'deck.pdf'
        writer = PdfWriter()
        for _ in colors:
            writer.add_blank_page(160, 90)
        with pdf.open('wb') as output:
            writer.write(output)
        rows = []
        for number, color in enumerate(colors, 1):
            png = directory / ('page-%d.png' % number)
            Image.new('RGB', (320, 180), color).save(png)
            rows.append(dict(self.link(png), page=number, pdf_sha256=gate.sha(pdf), width_px=320, height_px=180))
        source_hashes = {str(source.resolve()): gate.sha(source)}
        audit = {'schema':'beamer-layout-audit/v1','status':'complete','visual_review':'pending','signed_off':False,
                 'pdf':self.link(pdf),'physical_page_count':len(colors),
                 'coverage':{'expected_pages':list(range(1,len(colors)+1)), 'measured_pages':list(range(1,len(colors)+1)), 'unavailable_pages':[]},
                 'pages':[{'page':n,'status':'complete','visual_review':'pending','inventory':{},'measurements':{},'findings':[]} for n in range(1,len(colors)+1)],'findings':[]}
        audit_path=directory/'layout-audit.json';self.write(audit_path,audit)
        build = {'schema': 'beamer-build/v1', 'status': 'pending_visual_review', 'exit_code': 0,
                 'layout_audit':self.link(audit_path),
                 'signed_off': False, 'visual_review': 'pending', 'source_path': str(source.resolve()),
                 'pdf_path': str(pdf), 'pdf_sha256': gate.sha(pdf), 'physical_page_count': len(colors),
                 'renders': rows, 'input_hashes_before': source_hashes.copy(), 'input_hashes_after': source_hashes.copy(),
                 'dependency_hashes': source_hashes.copy(), 'warnings': [], 'findings': []}
        path = directory / 'build-report.json'
        self.write(path, build)
        return path, build

    def make_review(self, path, build):
        return {'schema': 'beamer-review/v1', 'scope': 'full', 'status': 'reviewed',
                'skill_lock':self.link(self.lock_path),
                'build_report_sha256': gate.sha(path), 'reviewer': 'fixture-primary', 'author': 'fixture-author',
                'audience': 'Synthetic audience context for a unit test.', 'unresolved': [],
                'pages': [{'page': row['page'], 'status': 'reviewed', 'render_sha256': row['sha256'],
                           'visual_checks': {key: 'Synthetic observation for ' + key for key in gate.CHECKS},
                           'optical_and_connectors': 'Synthetic glyph and connector observation.', 'closeups': []}
                          for row in build['renders']], 'diagnostics': [], 'font_exceptions': []}

    def crop(self, render, name, box=None):
        path = self.root / (name + '.png')
        box = box or [10, 20, 100, 80]
        with Image.open(render['path']) as image:
            image.crop(tuple(box)).save(path)
        return dict(self.link(path), render_sha256=render['sha256'], crop_box=box,
                    observation='Synthetic close-up observation in this fixture.')

    def check(self, ok=True, refresh=True):
        if refresh:
            self.write(self.build_path, self.build)
            self.review['build_report_sha256'] = gate.sha(self.build_path)
        self.write(self.review_path, self.review)
        result = gate.verify(self.build_path, self.review_path)
        self.assertEqual(result['status'], 'evidence_complete_pending_visual_signoff' if ok else 'failed', result)
        self.assertIs(result['signed_off'], False)
        return result

    def add_independent(self):
        self.build['findings'] = [{'category': 'page_geometry', 'page': 1}]
        self.write(self.build_path, self.build)
        peer = {'schema': 'beamer-independent-review/v1', 'reviewer': 'fixture-peer',
                'build_report_sha256': gate.sha(self.build_path), 'pdf_sha256': self.build['pdf_sha256'],
                'diagnostic': {'group': 'findings', 'index': 0}, 'page': 1,
                'render_sha256': self.build['renders'][0]['sha256'],
                'decision': 'visually_resolved', 'unresolved': [], 'local_viewed': True, 'full_page_viewed': True,
                'reference': 'Synthetic separate reviewer message reference for tests.',
                'local_observation': 'Synthetic local boundary observation for tests.',
                'full_page_observation': 'Synthetic whole-page observation for tests.',
                'closeup': self.crop(self.build['renders'][0], 'peer-crop')}
        peer_path = self.root / 'peer.json'
        self.write(peer_path, peer)
        self.review['diagnostics'] = [{'group': 'findings', 'index': 0, 'status': 'independently_resolved',
                                       'observation': 'Synthetic independent closure observation.',
                                       'independent_review': self.link(peer_path)}]
        return peer_path, peer

    def add_amendment(self):
        baseline_path, baseline_build = self.make_build('baseline')
        baseline_review = self.make_review(baseline_path, baseline_build)
        review_path = self.root / 'baseline-review.json'
        self.write(review_path, baseline_review)
        signoff = {'status': 'signed_off', 'scope': 'full', 'unresolved': [], 'reviewer': 'fixture-primary',
                   'reference': 'Synthetic historical full review event for unit tests.',
                   'review_sha256': gate.sha(review_path), 'build_report_sha256': gate.sha(baseline_path),
                   'pdf_sha256': baseline_build['pdf_sha256']}
        signoff_path = self.root / 'baseline-signoff.json'
        self.write(signoff_path, signoff)
        self.review.update(scope='amendment', user_reported_issue='Synthetic user issue: update page two annotation.',
                           baseline={'build': self.link(baseline_path), 'review': self.link(review_path),
                                     'signoff': self.link(signoff_path)})
        self.review['pages'][0] = {'page': 1, 'status': 'inherited',
                                   'render_sha256': self.build['renders'][0]['sha256']}
        return baseline_path, baseline_build, review_path, baseline_review, signoff_path, signoff

    def add_body_balance_fixture(self, category='body_vertical_balance_candidate', bounds=None):
        """Synthetic gate contract; this creates no human sign-off evidence."""
        peer_path, peer = self.add_independent()
        finding = {'category':category,'page':1,
                   'status':'pending_visual_review','bounds':bounds or [0,10,160,80],
                   'vertical_balance':{'direction':'top_heavy','upper_gap_pt':5,
                                       'lower_gap_pt':40,'candidate':True}}
        self.build['findings']=[finding]
        audit_path=Path(self.build['layout_audit']['path'])
        audit=json.loads(audit_path.read_text(encoding='utf8'))
        audit['findings']=[finding];audit['pages'][0]['findings']=[finding]
        self.write(audit_path,audit);self.build['layout_audit']=self.link(audit_path)
        self.write(self.build_path,self.build)
        peer['build_report_sha256']=gate.sha(self.build_path)
        peer['closeup']=self.crop(self.build['renders'][0],'body-region',[0,20,320,160])
        self.write(peer_path,peer)
        self.review['diagnostics'][0]['independent_review']=self.link(peer_path)
        return peer_path,peer

    def test_body_balance_candidate_continues_after_independent_visual_resolution(self):
        self.add_body_balance_fixture()
        self.check()
        self.assertTrue(self.build['findings'][0]['vertical_balance']['candidate'])
        self.assertEqual(self.build['findings'][0]['status'],'pending_visual_review')

    def test_body_container_current_independent_review_can_continue(self):
        self.add_body_balance_fixture('body_container_content_review');self.check()

    def fullpage_container_tiles(self):
        path,peer=self.add_body_balance_fixture('body_container_content_review',[0,0,160,90])
        peer.pop('closeup')
        peer['closeups']=[self.crop(self.build['renders'][0],'upper-tile',[0,0,320,100]),
                          self.crop(self.build['renders'][0],'lower-tile',[0,80,320,180])]
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        return path,peer

    def test_fullpage_container_can_close_with_two_true_local_tiles(self):
        self.fullpage_container_tiles();self.check()

    def test_fullpage_container_missing_tile_remains_pending(self):
        path,peer=self.fullpage_container_tiles();peer['closeups'].pop()
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_fullpage_container_whole_image_is_not_a_local_tile(self):
        path,peer=self.fullpage_container_tiles()
        peer['closeups']=[self.crop(self.build['renders'][0],'whole-instead',[0,0,320,180])]
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_fullpage_container_wrong_tile_pixels_remain_pending(self):
        path,peer=self.fullpage_container_tiles();tile=Path(peer['closeups'][0]['path'])
        Image.new('RGB',(320,100),'black').save(tile)
        peer['closeups'][0]['sha256']=gate.sha(tile)
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_fullpage_container_tiles_still_require_full_page_reading(self):
        path,peer=self.fullpage_container_tiles();peer['full_page_viewed']=False
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_body_container_author_observation_cannot_close(self):
        self.add_body_balance_fixture('body_container_content_review')
        self.review['diagnostics'][0].pop('independent_review');self.check(False)

    def test_body_container_unrelated_crop_cannot_close(self):
        path,peer=self.add_body_balance_fixture('body_container_content_review')
        peer['closeup']=self.crop(self.build['renders'][0],'unrelated-container-detail',[10,20,100,80])
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_body_container_full_page_and_content_still_required(self):
        path,peer=self.add_body_balance_fixture('body_container_content_review')
        peer['full_page_viewed']=False
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.review['pages'][0]['visual_checks']['content_sufficiency']=''
        self.check(False)

    def test_body_balance_without_independent_record_stays_pending(self):
        self.add_body_balance_fixture();self.review['diagnostics']=[]
        self.check(False)

    def test_body_balance_local_only_review_is_rejected(self):
        path,peer=self.add_body_balance_fixture();peer['full_page_viewed']=False
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_body_balance_resolution_still_requires_content_sufficiency(self):
        self.add_body_balance_fixture()
        self.review['pages'][0]['visual_checks']['content_sufficiency']=''
        self.check(False)

    def test_body_balance_unrelated_crop_cannot_close(self):
        path,peer=self.add_body_balance_fixture()
        peer['closeup']=self.crop(self.build['renders'][0],'unrelated-body-detail',[10,20,100,80])
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        self.check(False)

    def test_body_balance_null_crop_returns_recoverable_failure(self):
        path,peer=self.add_body_balance_fixture();peer['closeup']=None
        self.write(path,peer);self.review['diagnostics'][0]['independent_review']=self.link(path)
        result=self.check(False)
        self.assertIn('recheck',result['next_step'])
        self.assertFalse(any('AttributeError' in issue for issue in result['issues']))

    def add_font_exception(self):
        source = self.root / 'ten-source.tex'
        source.write_text('synthetic target font source at ten-equivalent size')
        path, build = self.make_build('ten', ('yellow',), source)
        exception = {'id': 'graph-label-A', 'page': 1, 'component': 'Synthetic special graph auxiliary label.',
                     'ten_equivalent_build': self.link(path), 'ten_equivalent_page': 1,
                     'ten_equivalent_pdf': self.link(Path(build['pdf_path'])),
                     'ten_equivalent_closeup': self.crop(build['renders'][0], 'ten-crop'),
                     'final_closeup': self.crop(self.build['renders'][0], 'final-font-crop'),
                     'ten_equivalent_source': dict(self.link(source), original_path=str(source.resolve()),
                                                   location='Synthetic target at source line one.')}
        for key in ('ten_equivalent_render_problem', 'ten_equivalent_target', 'ten_equivalent_method',
                    'measurement_uncertainty', 'necessity', 'layout_and_split_attempts', 'final_visual_observation'):
            exception[key] = 'Synthetic concrete evidence text for ' + key
        self.review['font_exceptions'] = [exception]
        return exception, path, build

    def test_complete_full_review_remains_pending_signoff(self):
        self.review['pages'][0]['closeups'] = [self.crop(self.build['renders'][0], 'detail')]
        self.check()

    def test_full_page_cannot_be_called_local_detail(self):
        self.review['pages'][0]['closeups'] = [self.crop(self.build['renders'][0], 'whole', [0, 0, 320, 180])]
        self.assertIn('whole-page image', str(self.check(False)['issues']))

    def test_rule_change_during_pixel_review_cannot_pass(self):
        fake_skill = self.root/'isolated-skill'
        (fake_skill/'scripts').mkdir(parents=True)
        rule = fake_skill/'SKILL.md'
        rule.write_text('original rule')
        lock = self.root/'isolated-lock.json'
        skill_state.snapshot(lock,fake_skill)
        self.review['skill_lock'] = self.link(lock)
        self.review['pages'][0]['closeups'] = [self.crop(self.build['renders'][0], 'actual-local')]
        original = gate.ImageChops.difference
        def mutate_after_initial_lock_check(a,b):
            rule.write_text('changed during verification')
            return original(a,b)
        from unittest.mock import patch
        with patch.object(gate,'__file__',str(fake_skill/'scripts/verify_beamer_review.py')), \
             patch.object(gate.ImageChops,'difference',side_effect=mutate_after_initial_lock_check):
            result = self.check(False)
        self.assertIn('Skill rules changed during verification',str(result['issues']))

    def test_independent_full_page_cannot_replace_local_crop(self):
        path, peer = self.add_independent()
        peer['closeup'] = self.crop(self.build['renders'][0], 'whole-peer', [0, 0, 320, 180])
        self.write(path, peer)
        self.review['diagnostics'][0]['independent_review'] = self.link(path)
        self.assertIn('whole-page image', str(self.check(False)['issues']))

    def mark_first_page_unavailable(self, finding=True):
        path = Path(self.build['layout_audit']['path'])
        audit = gate.load(path)
        audit['status'] = 'incomplete'
        audit['coverage'].update(measured_pages=[2], unavailable_pages=[1])
        row = audit['pages'][0]
        row.update(status='incomplete', inventory=None, measurements=None)
        if finding:
            f = {'category':'layout_measurement_unavailable', 'page':1,
                 'message':'Synthetic unavailable parser measurement.'}
            row['findings'] = [f]
            audit['findings'] = [f]
            self.build['findings'] = [f]
        self.write(path, audit)
        self.build['layout_audit'] = self.link(path)
        return path, audit

    def test_missing_measurement_cannot_disappear_without_finding(self):
        self.mark_first_page_unavailable(finding=False)
        self.assertIn('unavailable page needs', str(self.check(False)['issues']))

    def test_unavailable_measurement_has_working_independent_recovery(self):
        peer_path, peer = self.add_independent()
        self.mark_first_page_unavailable()
        self.write(self.build_path, self.build)
        peer['build_report_sha256'] = gate.sha(self.build_path)
        self.write(peer_path, peer)
        self.review['diagnostics'][0]['independent_review'] = self.link(peer_path)
        self.check()

    def test_audit_partition_and_status_must_match_actual_rows(self):
        path = Path(self.build['layout_audit']['path'])
        original = gate.load(path)
        for coverage in ({'expected_pages':[1,2], 'measured_pages':[1,2], 'unavailable_pages':[2]},
                         {'expected_pages':[1,2], 'measured_pages':[1], 'unavailable_pages':[]},
                         {'expected_pages':[1,2], 'measured_pages':[1,2], 'unavailable_pages':['2']}):
            audit = copy.deepcopy(original)
            audit['coverage'] = coverage
            self.write(path,audit);self.build['layout_audit']=self.link(path)
            self.assertIn('coverage is inconsistent',str(self.check(False)['issues']))

    def test_per_page_findings_must_reach_global_audit(self):
        path, audit = self.mark_first_page_unavailable()
        audit['findings'] = []
        self.write(path,audit);self.build['layout_audit']=self.link(path)
        self.assertIn('dropped a per-page finding', str(self.check(False)['issues']))

    def add_band_containers(self, build=None, title=False):
        build = build or self.build
        path = Path(build['layout_audit']['path'])
        audit = gate.load(path)
        rows = [{'container_id': f'p1:path:{index}', 'container_bounds': box, 'candidate': False}
                for index, box in enumerate(([0, 80, 50, 90], [50, 80, 110, 90], [110, 80, 160, 90]))]
        audit['pages'][0]['measurements']['footer_containers'] = rows
        if title:
            audit['pages'][0]['measurements']['title_containers'] = [
                {'container_id': 'p1:path:title', 'container_bounds': [0, 0, 160, 15], 'candidate': False}]
        self.write(path, audit)
        build['layout_audit'] = self.link(path)
        return rows

    def fill_band_checks(self, title=False):
        footer = self.crop(self.build['renders'][0], 'whole-footer', [0, 150, 320, 180])
        records = [{'container_id': f'p1:path:{index}',
                    'observation': f'Synthetic segment {index}: glyphs and local top/bottom margins inspected.',
                    'local_view': footer, 'full_page_return': True}
                   for index in range(3)]
        if title:
            records.append({'container_id': 'p1:path:title', 'observation': 'Synthetic title glyphs and complete pale container inspected.',
                            'local_view': self.crop(self.build['renders'][0], 'whole-title', [0, 0, 320, 35]),
                            'full_page_return': True})
        self.review['pages'][0]['container_checks'] = records
        return records

    def test_three_footer_segments_cannot_be_covered_by_one_record(self):
        self.add_band_containers()
        records = self.fill_band_checks()
        self.review['pages'][0]['container_checks'] = records[:1]
        result = self.check(False)
        self.assertIn('container check coverage incomplete', str(result['issues']))

    def test_every_segment_can_reference_same_true_whole_band_crop(self):
        self.add_band_containers(title=True)
        self.fill_band_checks(title=True)
        self.check()  # Old fixture has no DPI: actual 160x90 PDF maps to 320x180 PNG.
        self.build['dpi'] = 144
        self.check()

    def test_container_duplicate_extra_and_short_observation_are_rejected(self):
        self.add_band_containers()
        originals = self.fill_band_checks()
        mutations = [originals + [originals[0]],
                     originals + [dict(originals[0], container_id='not-in-audit')],
                     [dict(originals[0], observation='checked')] + originals[1:],
                     [dict(originals[0], full_page_return=False)] + originals[1:]]
        for records in mutations:
            with self.subTest(records=records):
                self.review['pages'][0]['container_checks'] = records
                self.check(False)

    def test_true_crop_of_another_segment_does_not_cover_target(self):
        self.add_band_containers()
        records = self.fill_band_checks()
        records[2]['local_view'] = self.crop(self.build['renders'][0], 'only-author', [0, 150, 110, 180])
        result = self.check(False)
        self.assertIn('does not cover the complete target container', str(result['issues']))

    def test_container_crop_pixels_and_render_hash_must_match_current_page(self):
        self.add_band_containers()
        records = self.fill_band_checks()
        bad = records[0]['local_view']
        Image.new('RGB', (320, 30), 'red').save(bad['path'])
        bad['sha256'] = gate.sha(bad['path'])
        self.assertIn('crop pixels differ', str(self.check(False)['issues']))
        self.fill_band_checks()[0]['local_view']['render_sha256'] = '0' * 64
        self.assertIn('parent render differs', str(self.check(False)['issues']))

    def test_no_identified_containers_keeps_existing_full_page_checks(self):
        self.assertNotIn('container_checks', self.review['pages'][0])
        self.check()
        self.review['pages'][0]['visual_checks'].pop('container_balance')
        self.assertIn('container_balance', str(self.check(False)['issues']))

    def test_template_creates_pending_record_for_every_title_and_footer_container(self):
        self.add_band_containers(title=True)
        self.write(self.build_path, self.build)
        template = gate.template(self.build_path)
        records = template['pages'][0]['container_checks']
        self.assertEqual({r['container_id'] for r in records}, {'p1:path:0', 'p1:path:1', 'p1:path:2', 'p1:path:title'})
        self.assertTrue(all(r['status'] == 'pending' and r['observation'] == '' and r['full_page_return'] is False for r in records))
        self.assertTrue(all('whole-band crop' in r['instruction'] and 'local_view' in r for r in records))
        self.review['pages'][0]['container_checks'] = records
        result = self.check(False)
        self.assertIn('container remains pending', str(result['issues']))

    def test_legacy_baseline_and_unchanged_inheritance_do_not_need_new_records(self):
        path, old_build, review_path, old_review, signoff_path, signoff = self.add_amendment()
        self.add_band_containers(old_build)
        self.write(path, old_build)
        old_review['build_report_sha256'] = gate.sha(path)
        self.write(review_path, old_review)
        signoff.update(review_sha256=gate.sha(review_path), build_report_sha256=gate.sha(path))
        self.write(signoff_path, signoff)
        self.review['baseline'] = {'build': self.link(path), 'review': self.link(review_path), 'signoff': self.link(signoff_path)}
        self.add_band_containers()
        self.check()
        # Newly reviewed/full pages get the new coverage rule; inheritance
        # compatibility is tied to validated historical, identical evidence.
        self.review['pages'][0] = copy.deepcopy(old_review['pages'][0])
        self.assertIn('container check coverage incomplete', str(self.check(False)['issues']))

    def test_content_and_density_checks_required_despite_clean_geometry(self):
        for key in ('content_reading', 'content_sufficiency', 'density_and_balance', 'regional_balance'):
            saved = self.review['pages'][0]['visual_checks'].pop(key)
            result = self.check(False)
            self.assertIn(key, str(result['issues']))
            self.review['pages'][0]['visual_checks'][key] = saved

    def test_independent_layout_resolution_does_not_waive_content(self):
        self.add_independent()
        self.review['pages'][0]['visual_checks'].pop('content_sufficiency')
        result = self.check(False)
        self.assertIn('content_sufficiency', str(result['issues']))

    def test_reported_content_gap_remains_unresolved(self):
        self.review['unresolved'] = ['The worked example and supporting data were deleted to fit the layout.']
        self.check(False)

    def test_layout_audit_missing_or_stale_rejected(self):
        audit=self.build.pop('layout_audit');self.check(False)
        self.build['layout_audit']=dict(audit,sha256='0'*64);self.check(False)

    def test_layout_audit_findings_cannot_be_dropped(self):
        path=Path(self.build['layout_audit']['path']);audit=gate.load(path)
        audit['findings']=[{'category':'small_text_candidate','page':1}]
        self.write(path,audit);self.build['layout_audit']=self.link(path);self.check(False)

    def test_missing_or_wrong_skill_lock_rejected(self):
        lock=self.review.pop('skill_lock');self.check(False)
        self.review['skill_lock']=lock
        data=gate.load(self.lock_path);data['files']['SKILL.md']='0'*64
        self.write(self.lock_path,data);self.review['skill_lock']=self.link(self.lock_path);self.check(False)

    def test_every_physical_overlay_page_is_required(self):
        self.review['pages'].pop()
        self.check(False)

    def test_render_coverage_and_duplicates_rejected(self):
        self.build['renders'][1]['page'] = 1
        self.check(False)

    def test_pdf_page_count_is_actual(self):
        self.build['physical_page_count'] = 3
        self.check(False)

    def test_current_pdf_hash_mismatch_rejected(self):
        self.build['pdf_sha256'] = '0' * 64
        self.check(False)

    def test_current_image_hash_mismatch_rejected(self):
        Image.new('RGB', (320, 180), 'red').save(self.build['renders'][0]['path'])
        self.check(False)

    def test_changed_input_and_inconsistent_snapshots_rejected(self):
        original = self.source.read_text()
        self.source.write_text('changed source')
        self.check(False)
        self.source.write_text(original)
        self.build['input_hashes_after'] = {}
        self.check(False)

    def test_empty_recorder_dependencies_are_compatible(self):
        self.build['dependency_hashes'] = {}
        self.check()

    def test_crop_pixels_must_match_parent_even_when_hash_is_current(self):
        crop = self.crop(self.build['renders'][0], 'bad-crop')
        Image.new('RGB', (90, 60), 'red').save(crop['path'])
        crop['sha256'] = gate.sha(crop['path'])
        self.review['pages'][0]['closeups'] = [crop]
        result = self.check(False)
        self.assertTrue(any('crop pixels differ' in issue for issue in result['issues']))

    def test_ordinary_warning_can_be_visually_recorded(self):
        self.build['warnings'] = [{'category': 'underfull_box', 'message': 'Synthetic diagnostic'}]
        self.review['diagnostics'] = [{'group': 'warnings', 'index': 0, 'status': 'visually_checked',
                                      'observation': 'Synthetic visual observation with adequate spacing.'}]
        self.check()

    def test_rule_finding_accepts_separate_linked_independent_evidence(self):
        self.add_independent()
        self.check()

    def test_inline_author_claim_cannot_close_finding(self):
        _, peer = self.add_independent()
        self.review['diagnostics'][0]['independent_review'] = peer
        self.check(False)

    def test_primary_or_author_cannot_act_as_independent_reviewer(self):
        path, peer = self.add_independent()
        for reviewer in (' FIXTURE-PRIMARY ', 'fixture-author'):
            peer['reviewer'] = reviewer
            self.write(path, peer)
            self.review['diagnostics'][0]['independent_review'] = self.link(path)
            self.check(False)
        peer['reviewer'] = 'fixture-peer'
        self.write(path, peer)
        self.review['diagnostics'][0]['independent_review'] = self.link(path)
        self.review.pop('author')
        self.check(False)

    def test_peer_must_target_current_finding_and_both_view_scales(self):
        path, peer = self.add_independent()
        peer['diagnostic']['index'] = 1
        peer['full_page_viewed'] = False
        self.write(path, peer)
        self.review['diagnostics'][0]['independent_review'] = self.link(path)
        self.check(False)

    def test_full_baseline_allows_unchanged_page_inheritance(self):
        self.add_amendment()
        self.check()

    def test_baseline_source_can_change_but_current_source_must_match(self):
        self.add_amendment()
        self.source.write_text('new source revision after baseline signoff')
        value = gate.sha(self.source)
        for key in ('input_hashes_before', 'input_hashes_after', 'dependency_hashes'):
            self.build[key] = {str(self.source.resolve()): value}
        self.check()

    def test_inherited_image_must_be_identical(self):
        self.add_amendment()
        render = self.build['renders'][0]
        Image.new('RGB', (320, 180), 'red').save(render['path'])
        render['sha256'] = gate.sha(render['path'])
        self.review['pages'][0]['render_sha256'] = render['sha256']
        self.check(False)

    def test_baseline_claimed_reviewed_status_is_insufficient(self):
        _, _, old_path, old, signoff_path, signoff = self.add_amendment()
        old['pages'][0]['visual_checks'] = {}
        self.write(old_path, old)
        signoff['review_sha256'] = gate.sha(old_path)
        self.write(signoff_path, signoff)
        self.review['baseline']['review'] = self.link(old_path)
        self.review['baseline']['signoff'] = self.link(signoff_path)
        self.check(False)

    def test_baseline_missing_or_stale_image_is_rejected(self):
        _, old_build, *_ = self.add_amendment()
        Path(old_build['renders'][0]['path']).unlink()
        self.check(False)

    def test_font_exception_has_traceable_baseline_and_current_crops(self):
        self.add_font_exception()
        self.check()

    def test_font_exception_cannot_use_unrelated_current_crop(self):
        exception, _, _ = self.add_font_exception()
        exception['final_closeup'] = exception['ten_equivalent_closeup']
        self.check(False)

    def test_font_exception_cannot_use_unrelated_ten_pdf_or_source(self):
        exception, _, _ = self.add_font_exception()
        exception['ten_equivalent_pdf'] = self.link(Path(self.build['pdf_path']))
        exception['ten_equivalent_source']['original_path'] = str(self.source)
        self.check(False)

    def test_font_exception_rejects_unstable_ten_equivalent_source(self):
        exception, path, build = self.add_font_exception()
        build['input_hashes_after'] = {}
        self.write(path, build)
        exception['ten_equivalent_build'] = self.link(path)
        result = self.check(False)
        self.assertTrue(any('Ten-equivalent build input snapshots differ' in issue for issue in result['issues']))

    def test_malformed_inputs_return_structured_failure(self):
        for key, value in [('pages', [{'page': []}]), ('diagnostics', [{'group': [], 'index': {}}]),
                           ('font_exceptions', [{'id': []}]), ('pages', [None])]:
            with self.subTest(key=key, value=value):
                saved = copy.deepcopy(self.review)
                self.review[key] = value
                self.check(False)
                self.review = saved

    def test_malformed_json_and_missing_files_do_not_raise(self):
        self.review_path.write_text('{broken')
        self.assertEqual(gate.verify(self.build_path, self.review_path)['status'], 'failed')
        self.assertEqual(gate.verify(self.root / 'missing.json', self.review_path)['status'], 'failed')

    def test_template_is_complete_unreviewed_and_rejected_by_validator(self):
        self.build['warnings'] = [{'category': 'underfull_box'}]
        self.build['findings'] = [{'category': 'page_geometry', 'page': 1}]
        self.write(self.build_path, self.build)
        with contextlib.redirect_stdout(io.StringIO()):
            code = gate.main(['--template', str(self.build_path), str(self.review_path)])
        self.assertEqual(code, 0)
        template = gate.load(self.review_path)
        self.assertEqual(template['status'], 'unreviewed')
        self.assertEqual(len(template['pages']), 2)
        self.assertEqual(len(template['pages'][0]['visual_checks']), 14)
        self.assertTrue(all(value == '' for value in template['pages'][0]['visual_checks'].values()))
        self.assertEqual([row['status'] for row in template['diagnostics']], ['pending', 'pending'])
        self.assertEqual(template['font_exceptions'], [])
        self.assertEqual(gate.verify(self.build_path, self.review_path)['status'], 'failed')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(['--template', str(self.build_path), str(self.review_path)]), 2)

    def test_three_argument_cli_keeps_evidence_and_writes_pending_result(self):
        self.write(self.review_path, self.review)
        output = self.root / 'check.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = gate.main([str(self.build_path), str(self.review_path), str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(gate.load(output)['status'], 'evidence_complete_pending_visual_signoff')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main([str(self.build_path), str(self.review_path), str(output)]), 2)


if __name__ == '__main__':
    unittest.main()
