"""Generator metadata preparation preserves document content and raw images."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from lxml import etree
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, EncodedStreamObject, NameObject, NumberObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

import pdf_generator_metadata as metadata

XMP = b'''<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/"
   xmlns:pdf="http://ns.adobe.com/pdf/1.3/" xmlns:dc="http://purl.org/dc/elements/1.1/"
   xmlns:custom="https://example.test/custom/" xmp:CreatorTool="Test Creator"
   pdf:Producer="Test Producer" xmp:CreateDate="2026-01-02T03:04:05Z" custom:Flag="preserve me">
   <xmp:CreatorTool>Another test creator</xmp:CreatorTool>
   <pdf:Producer>Another test producer</pdf:Producer>
   <xmp:ModifyDate>2026-02-03T04:05:06Z</xmp:ModifyDate>
   <dc:creator><rdf:Seq><rdf:li>Named Author</rdf:li></rdf:Seq></dc:creator>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Named Title</rdf:li></rdf:Alt></dc:title>
   <dc:description>Retained subject text</dc:description>
   <custom:Producer>Unrelated namespaced property</custom:Producer>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>'''


def make_fixture(directory, with_xmp=True):
    """Three actual pages with JPEG, alpha-PNG, text, URI links and outlines."""
    directory = Path(directory)
    image = Image.new('RGB', (90, 60))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), (x * 2, y * 3, (x + y) % 255))
    jpeg = io.BytesIO()
    image.save(jpeg, format='JPEG', quality=87)
    jpeg.seek(0)
    alpha = Image.new('RGBA', (60, 60), (0, 150, 210, 170))
    png = io.BytesIO()
    alpha.save(png, format='PNG')
    png.seek(0)
    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=(480, 270), pageCompression=1)
    canvas.setAuthor('Named Author')
    canvas.setTitle('Named Title')
    canvas.setSubject('Retained subject')
    canvas.setKeywords('one, two, preserved')
    canvas.setCreator('Fixture Creator')
    canvas.setProducer('Fixture Producer')
    for number in range(1, 4):
        canvas.bookmarkPage('page-' + str(number))
        canvas.addOutlineEntry('Section ' + str(number), 'page-' + str(number), level=0)
        canvas.setFont('Helvetica', 18)
        canvas.drawString(25, 235, 'Metadata preservation page ' + str(number))
        canvas.drawImage(ImageReader(jpeg), 25, 80, 180, 120)
        canvas.drawImage(ImageReader(png), 250, 95, 100, 100, mask='auto')
        canvas.linkURL('https://example.test/page/' + str(number), (25, 225, 350, 250))
        canvas.showPage()
    canvas.save()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(stream.getvalue())))
    writer.add_metadata({'/CustomProperty': 'Do not alter', '/Trapped': '/False'})
    if with_xmp:
        xmp = DecodedStreamObject()
        xmp.set_data(XMP)
        xmp[NameObject('/Type')] = NameObject('/Metadata')
        xmp[NameObject('/Subtype')] = NameObject('/XML')
        writer.root_object[NameObject('/Metadata')] = writer._add_object(xmp)
    path = directory / 'deck.pdf'
    with path.open('wb') as output:
        writer.write(output)
    return path


class GeneratorMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='pdf-metadata-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = make_fixture(self.root)

    def prepare(self):
        return metadata.prepare_generator_metadata(self.path, owned_run_dir=self.root)

    def test_only_info_and_xmp_generator_fields_are_removed(self):
        reader = PdfReader(self.path)
        before = {key: value for key, value in reader.metadata.items() if key not in metadata.INFO_FIELDS}
        result = self.prepare()
        after = PdfReader(self.path)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(set(result['removed_fields']), {'Info:/Creator', 'Info:/Producer', 'XMP:xmp:CreatorTool', 'XMP:pdf:Producer'})
        self.assertEqual(dict(after.metadata), before)
        data = after.trailer['/Root']['/Metadata'].get_data()
        _, removed = metadata.clean_xmp(data)
        self.assertEqual(removed, [])
        self.assertEqual(metadata._xml_semantics(XMP), metadata._xml_semantics(data))
        xml = etree.fromstring(data)
        self.assertIn('Named Author', ''.join(xml.itertext()))
        self.assertIn('Named Title', ''.join(xml.itertext()))
        self.assertIn('Unrelated namespaced property', ''.join(xml.itertext()))
        self.assertIn(b'2026-01-02T03:04:05Z', data)
        self.assertIn(b'2026-02-03T04:05:06Z', data)

    def test_raw_encoded_images_text_links_outlines_and_pages_preserved(self):
        before = metadata.semantic_snapshot(PdfReader(self.path, strict=True))
        self.assertGreaterEqual(sum(before['encoded_image_hash_counts'].values()), 3)
        self.assertEqual(before['physical_page_count'], 3)
        result = self.prepare()
        after = PdfReader(self.path, strict=True)
        self.assertEqual(metadata.semantic_snapshot(after), before)
        self.assertEqual(len(after.outline), 3)
        self.assertEqual(after.pages[1]['/Annots'][0].get_object()['/A']['/URI'], 'https://example.test/page/2')
        self.assertEqual(result['preservation_check'], before)
        self.assertFalse(result['images_reencoded'])
        self.assertEqual(metadata.file_hash(self.root / 'raw-compiled.pdf'), result['before_sha256'])

    def test_repeated_preparation_is_byte_identical_no_rewrite(self):
        self.prepare()
        before = self.path.stat().st_mtime_ns, metadata.file_hash(self.path)
        result = self.prepare()
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['removed_fields'], [])
        self.assertEqual((self.path.stat().st_mtime_ns, metadata.file_hash(self.path)), before)

    def test_absent_targets_do_not_rewrite(self):
        reader = PdfReader(self.path)
        writer = PdfWriter(clone_from=reader)
        for key in metadata.INFO_FIELDS:
            writer._info.pop(key, None)
        writer.root_object.pop('/Metadata', None)
        with self.path.open('wb') as output:
            writer.write(output)
        original = self.path.read_bytes()
        result = self.prepare()
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse((self.root / 'raw-compiled.pdf').exists())

    def test_corrupt_pdf_is_not_replaced(self):
        self.path.write_bytes(b'%PDF-1.7\ncorrupted input')
        original = self.path.read_bytes()
        with self.assertRaises(Exception):
            self.prepare()
        self.assertEqual(self.path.read_bytes(), original)

    def test_changed_protected_semantics_prevent_replacement(self):
        original = self.path.read_bytes()
        actual = metadata.semantic_snapshot
        calls = []
        def altered(reader):
            snapshot = actual(reader)
            calls.append(True)
            if len(calls) == 2:
                snapshot['semantic_sha256'] = '0' * 64
            return snapshot
        with patch.object(metadata, 'semantic_snapshot', side_effect=altered), self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.metadata-*.pdf')), [])

    def test_preexisting_raw_backup_is_preserved(self):
        backup = self.root / 'raw-compiled.pdf'
        backup.write_bytes(b'existing diagnostic')
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(backup.read_bytes(), b'existing diagnostic')
        self.assertEqual(self.path.read_bytes(), original)

    def test_outside_owned_run_is_rejected(self):
        with self.assertRaises(ValueError):
            metadata.prepare_generator_metadata(self.path, owned_run_dir=self.root / 'another-run')

    def test_grouped_page_tree_flattening_preserves_actual_page_semantics(self):
        writer = PdfWriter(clone_from=PdfReader(self.path))
        root = writer.root_object['/Pages']
        original_kids = list(root['/Kids'])
        groups = []
        for kids in (original_kids[:1], original_kids[1:]):
            branch = DictionaryObject({NameObject('/Type'): NameObject('/Pages'),
                                       NameObject('/Count'): NumberObject(len(kids)),
                                       NameObject('/Kids'): ArrayObject(kids),
                                       NameObject('/Parent'): root.indirect_reference})
            reference = writer._add_object(branch)
            for child in kids:
                child.get_object()[NameObject('/Parent')] = reference
            groups.append(reference)
        root[NameObject('/Kids')] = ArrayObject(groups)
        with self.path.open('wb') as output:
            writer.write(output)
        self.assertEqual(PdfReader(self.path).trailer['/Root']['/Pages']['/Kids'][0].get_object()['/Type'], '/Pages')
        before = metadata.semantic_snapshot(PdfReader(self.path))
        result = self.prepare()
        after = PdfReader(self.path)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(metadata.semantic_snapshot(after), before)
        self.assertEqual(len(after.pages), 3)
        self.assertEqual(len(after.outline), 3)

    def test_metadata_preparation_does_not_decode_image_streams(self):
        original = EncodedStreamObject.get_data
        def reject_image_decode(stream):
            if stream.get('/Subtype') == '/Image':
                raise AssertionError('Image decoding is forbidden in metadata preparation')
            return original(stream)
        with patch.object(EncodedStreamObject, 'get_data', reject_image_decode):
            self.assertEqual(self.prepare()['status'], 'prepared')

    def test_pdf_17_header_and_catalog_version_survive_with_transparent_images(self):
        writer = PdfWriter(clone_from=PdfReader(self.path))
        writer.pdf_header = '%PDF-1.7'
        writer.root_object[NameObject('/Version')] = NameObject('/1.7')
        with self.path.open('wb') as output:
            writer.write(output)
        before = PdfReader(self.path)
        self.assertEqual(before.pdf_header, '%PDF-1.7')
        self.assertTrue(any('/SMask' in reference.get_object()
                            for reference in before.pages[0]['/Resources']['/XObject'].values()))
        baseline = metadata.semantic_snapshot(before)
        result = self.prepare()
        after = PdfReader(self.path)
        self.assertEqual(after.pdf_header, '%PDF-1.7')
        self.assertEqual(after.trailer['/Root']['/Version'], '/1.7')
        self.assertEqual(result['preservation_check']['pdf_header'], '%PDF-1.7')
        self.assertEqual(metadata.semantic_snapshot(after), baseline)


if __name__ == '__main__':
    unittest.main()
