"""Picture fidelity across preparation, building, and delivery shell changes."""
import json
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation
from pptx.util import Inches

# The test runner copies cases beside production scripts; also support direct runs.
SCRIPTS = Path(__file__).resolve().parent
if not (SCRIPTS / 'pptx_image_fidelity.py').is_file():
    SCRIPTS = Path(__file__).resolve().parents[2] / 'skill/my-ppt-skill/scripts'
sys.path.insert(0, str(SCRIPTS))
import pptx_image_fidelity as fidelity
import pptx_delivery_shell as shell


def image_bytes(kind='PNG'):
    stream = BytesIO()
    Image.new('RGB', (1600, 900), '#245877').save(stream, format=kind)
    return stream.getvalue()


def deck_bytes():
    deck = Presentation()
    deck._element.set('autoCompressPictures', '1')
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for index, kind in enumerate(('PNG', 'JPEG')):
        slide.shapes.add_picture(BytesIO(image_bytes(kind)), Inches(index * 3), Inches(1), width=Inches(3))
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def replace_parts(data, updates):
    result = BytesIO()
    with ZipFile(BytesIO(data)) as original, ZipFile(result, 'w') as archive:
        for item in original.infolist():
            archive.writestr(item, updates.get(item.filename, original.read(item)))
    return result.getvalue()


class ImageFidelityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.pptx'
        self.original = deck_bytes()
        self.source.write_bytes(self.original)

    def test_media_and_every_other_part_remain_identical(self):
        result, report = fidelity.transform(self.original)
        self.assertEqual('0', report['auto_compress_pictures'])
        before, _, _ = fidelity._parts(self.original)
        after, _, _ = fidelity._parts(result)
        self.assertEqual(set(before), set(after))
        self.assertEqual([fidelity.PRESENTATION], [key for key in before if before[key] != after[key]])
        self.assertEqual([], fidelity.verify(self.original, result))
        media = [before[name] for name in before if name.startswith('ppt/media/')]
        self.assertIn(image_bytes('PNG'), media)
        self.assertIn(image_bytes('JPEG'), media)

    def test_threshold_strictly_over_twenty_million_and_no_input(self):
        part = next(name for name in fidelity.media_manifest(self.original) if name.endswith('.png'))
        for size, count in ((19_999_999, 0), (20_000_000, 0), (20_000_001, 1)):
            with self.subTest(size=size), patch('builtins.input', side_effect=AssertionError('Must not wait')):
                data = replace_parts(self.original, {part: b'x' * size})
                result, report = fidelity.transform(data)
                self.assertEqual(count, len(report['large_images']))
                self.assertEqual([], fidelity.verify(data, result))
                self.assertEqual(size, report['media'][part]['bytes'])

    def test_source_untouched_and_repeat_is_byte_identical(self):
        target = self.root / 'candidate.pptx'
        report = fidelity.prepare(self.source, target)
        first = target.read_bytes()
        self.assertEqual(self.original, self.source.read_bytes())
        self.assertEqual(report, fidelity.prepare(self.source, target))
        self.assertEqual(first, target.read_bytes())
        self.assertEqual(first, fidelity.transform(first)[0])
        self.assertEqual([], fidelity.verify(self.original, first))

    def test_refuse_same_path_or_existing_other_content(self):
        with self.assertRaisesRegex(ValueError, 'separate copy'):
            fidelity.prepare(self.source, self.source)
        target = self.root / 'existing.pptx'
        target.write_bytes(b'keep user data')
        with self.assertRaises(FileExistsError):
            fidelity.prepare(self.source, target)
        self.assertEqual(b'keep user data', target.read_bytes())
        self.assertEqual(self.original, self.source.read_bytes())

    def test_false_setting_is_already_disabled(self):
        data, _ = fidelity.transform(self.original)
        parts, _, _ = fidelity._parts(data)
        data = replace_parts(data, {fidelity.PRESENTATION: parts[fidelity.PRESENTATION].replace(b'autoCompressPictures="0"', b'autoCompressPictures="false"')})
        self.assertEqual(data, fidelity.transform(data)[0])
        self.assertEqual([], fidelity.verify(self.original, data))

    def test_detect_reencoding_even_same_dimensions(self):
        data, _ = fidelity.transform(self.original)
        part = next(name for name in fidelity.media_manifest(data) if name.endswith('.png'))
        changed = replace_parts(data, {part: image_bytes('JPEG')})
        self.assertEqual(['Embedded media changed: ' + part], fidelity.verify(self.original, changed))

    def test_thumbnail_jpeg_and_shell_fingerprint_unchanged(self):
        candidate, _ = fidelity.transform(self.original)
        final, proof = shell.transform(candidate, image_bytes())
        self.assertEqual([], shell.verify_shell(final, image_bytes()))
        self.assertEqual([], fidelity.verify(candidate, final))
        self.assertEqual(proof['content_fingerprint_before'], proof['content_fingerprint_after'])
        parts, _, _ = fidelity._parts(final)
        with Image.open(BytesIO(parts[proof['thumbnail_part']])) as thumbnail:
            self.assertEqual('JPEG', thumbnail.format)
            self.assertEqual((320, 180), thumbnail.size)

    def test_builder_preserves_source_images_and_sets_document_property(self):
        edits = self.root / 'edits.json'
        edits.write_text(json.dumps({'selected_slides': [1], 'edits': []}), encoding='utf8')
        target = self.root / 'built.pptx'
        child = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'build_pptx.py'),
                                str(self.source), str(edits), str(target)],
                               capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(0, child.returncode, child.stdout + child.stderr)
        self.assertEqual(self.original, self.source.read_bytes())
        self.assertEqual([], fidelity.verify(self.original, target.read_bytes()))

    def test_cli_preparation_and_verification(self):
        target = self.root / 'candidate.pptx'
        command = [sys.executable, '-B', str(SCRIPTS / 'pptx_image_fidelity.py')]
        prepared = subprocess.run(command + ['prepare', '--input', str(self.source), '--output', str(target)],
                                  capture_output=True, text=True, encoding='utf8', stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        self.assertEqual('0', json.loads(prepared.stdout)['auto_compress_pictures'])
        checked = subprocess.run(command + ['verify', '--reference', str(self.source), '--pptx', str(target)],
                                 capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertEqual([], json.loads(checked.stdout)['errors'])


if __name__ == '__main__':
    unittest.main()
