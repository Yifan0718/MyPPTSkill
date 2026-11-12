"""Remove only generator identities from a task-owned compiled PDF.

No image recompression, downsampling, content transformation, or automatic date
updates are performed. A validated clone replaces only the current run's deck.pdf.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from lxml import etree
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, ByteStringObject,
                           DictionaryObject, FloatObject, IndirectObject,
                           NameObject, NullObject, StreamObject, TextStringObject)

INFO_FIELDS = ('/Creator', '/Producer')
XMP_FIELDS = {
    '{http://ns.adobe.com/xap/1.0/}CreatorTool': 'xmp:CreatorTool',
    '{http://ns.adobe.com/pdf/1.3/}Producer': 'pdf:Producer',
}


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def clean_xmp(data):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    tree = etree.fromstring(data, parser).getroottree()
    if tree.docinfo.doctype:
        raise ValueError('XMP with a DTD requires explicit inspection before metadata preparation.')
    removed = set()
    for element in list(tree.iter()):
        for attribute in list(element.attrib):
            if attribute in XMP_FIELDS:
                del element.attrib[attribute]
                removed.add(XMP_FIELDS[attribute])
        if element.tag in XMP_FIELDS:
            parent = element.getparent()
            if parent is None:
                raise ValueError('Generator property cannot be the XMP document root.')
            # Preserve formatting text belonging to the surrounding RDF document.
            if element.tail:
                previous = element.getprevious()
                if previous is None:
                    parent.text = (parent.text or '') + element.tail
                else:
                    previous.tail = (previous.tail or '') + element.tail
            parent.remove(element)
            removed.add(XMP_FIELDS[element.tag])
    return etree.tostring(tree, encoding='utf-8'), sorted(removed)


def _xml_semantics(data):
    cleaned, _ = clean_xmp(data)
    root = etree.fromstring(cleaned, etree.XMLParser(resolve_entities=False, no_network=True))
    def node(element):
        # Namespace-qualified names preserve property identity independently of
        # serializer prefix choice. Ignore only RDF indentation whitespace.
        tag = element.tag if isinstance(element.tag, str) else str(element.tag)
        text = element.text if element.text and element.text.strip() else None
        tail = element.tail if element.tail and element.tail.strip() else None
        return [tag, sorted(element.attrib.items()), text, tail, [node(child) for child in element]]
    return node(root)


def semantic_snapshot(reader):
    """Fingerprint the catalog graph, content, links/outlines, Info, XMP and images."""
    seen = {}
    physical_pages = list(reader.pages)
    page_numbers = {(page.indirect_reference.idnum, page.indirect_reference.generation): number
                    for number, page in enumerate(physical_pages, 1)}
    def value(obj, catalog=False, page_root=False):
        if isinstance(obj, IndirectObject):
            key = (obj.idnum, obj.generation)
            if key in page_numbers and not page_root:
                return ['page_reference', page_numbers[key]]
            if key in seen:
                return ['ref', seen[key]]
            number = len(seen)
            seen[key] = number
            target = obj.get_object()
            if target is None:
                raise ValueError('PDF contains an unresolved object.')
            return ['object', number, value(target, catalog, page_root)]
        if isinstance(obj, DictionaryObject):
            result = ['dictionary', [[str(key), value(obj.raw_get(key))] for key in sorted(obj)
                                      if not (catalog and key in ('/Metadata', '/Pages'))
                                      and not (page_root and key == '/Parent')]]
            if isinstance(obj, StreamObject):
                result += ['encoded_sha256', hashlib.sha256(obj._data).hexdigest()]
            return result
        if isinstance(obj, ArrayObject):
            return ['array', [value(item) for item in obj]]
        if isinstance(obj, ByteStringObject):
            return ['bytes', bytes(obj).hex()]
        if isinstance(obj, BooleanObject):
            return ['boolean', obj.value]
        if isinstance(obj, NullObject) or obj is None:
            return ['null']
        if isinstance(obj, NameObject):
            return ['name', str(obj)]
        if isinstance(obj, TextStringObject):
            return ['text', str(obj)]
        if isinstance(obj, FloatObject) or isinstance(obj, float):
            return ['number', round(float(obj), 6)]
        if isinstance(obj, int):
            return ['number', obj]
        raise ValueError('Unsupported PDF value while verifying metadata preparation: ' + type(obj).__name__)

    images = Counter()
    seen_images = set()
    for generation, offsets in reader.xref.items():
        for identifier in offsets:
            if identifier:
                obj = reader.get_object(IndirectObject(identifier, generation, reader))
                if obj is None:
                    raise ValueError('PDF contains an unresolved xref object.')
                if isinstance(obj, StreamObject) and obj.get('/Subtype') == '/Image':
                    images[hashlib.sha256(obj._data).hexdigest()] += 1
                    seen_images.add((identifier, generation))
    for identifier in reader.xref_objStm:
        if (identifier, 0) not in seen_images:
            obj = reader.get_object(IndirectObject(identifier, 0, reader))
            if isinstance(obj, StreamObject) and obj.get('/Subtype') == '/Image':
                images[hashlib.sha256(obj._data).hexdigest()] += 1
    pages = []
    for page in physical_pages:
        content = page.get_contents()
        pages.append({'media_box': [round(float(number), 6) for number in page.mediabox],
                      'crop_box': [round(float(number), 6) for number in page.cropbox],
                      'rotation': page.rotation,
                      'text_sha256': hashlib.sha256(page.extract_text().encode('utf8')).hexdigest(),
                      'content_sha256': hashlib.sha256(content.get_data() if content is not None else b'').hexdigest()})
    if not pages:
        raise ValueError('PDF contains no pages.')
    # Page accessors may materialize inherited box entries. Fingerprint after
    # those accesses so both sides see the same normalized catalog structure.
    catalog = value(reader.trailer.raw_get('/Root'), catalog=True)
    page_objects = [value(page, page_root=True) for page in physical_pages]
    # Clone legitimately flattens /Pages storage nodes. Preserve every effective
    # page property and canonical page destination, not the grouping topology.
    # Unusual non-inheritable tree properties remain protected separately.
    tree_extras = []
    def inspect_tree(node):
        node = node.get_object()
        if node.get('/Type') != '/Pages':
            return
        extra = DictionaryObject({key: node.raw_get(key) for key in node
                                  if key not in ('/Type', '/Parent', '/Kids', '/Count',
                                                 '/Resources', '/MediaBox', '/CropBox', '/Rotate')})
        if extra:
            tree_extras.append(value(extra))
        for child in node.get('/Kids', []):
            inspect_tree(child)
    inspect_tree(reader.trailer['/Root']['/Pages'])
    info = reader.trailer.get('/Info')
    info = info.get_object() if info is not None else {}
    info_value = [[str(key), value(info.raw_get(key))] for key in sorted(info) if key not in INFO_FIELDS]
    metadata = reader.trailer['/Root'].get('/Metadata')
    xmp = _xml_semantics(metadata.get_object().get_data()) if metadata is not None else None
    semantic = {'pdf_header': reader.pdf_header, 'catalog': catalog, 'page_objects': page_objects,
                'page_tree_extra_properties': tree_extras, 'info': info_value, 'xmp': xmp}
    return {'pdf_header': reader.pdf_header, 'physical_page_count': len(pages), 'pages': pages,
            'encoded_image_hash_counts': dict(sorted(images.items())),
            'semantic_sha256': hashlib.sha256(json.dumps(semantic, ensure_ascii=True, sort_keys=True).encode('utf8')).hexdigest()}


def prepare_generator_metadata(pdf_path, *, owned_run_dir):
    path, run_dir = Path(pdf_path).resolve(), Path(owned_run_dir).resolve()
    if path.parent != run_dir or path.name != 'deck.pdf':
        raise ValueError('Metadata preparation only accepts deck.pdf inside its explicitly owned run directory.')
    before_hash = file_hash(path)
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError('Encrypted PDF metadata is not rewritten.')
    info = reader.trailer.get('/Info')
    info = info.get_object() if info is not None else {}
    removed = ['Info:' + key for key in INFO_FIELDS if key in info]
    metadata = reader.trailer['/Root'].get('/Metadata')
    cleaned_xmp, xmp_removed = None, []
    if metadata is not None:
        cleaned_xmp, xmp_removed = clean_xmp(metadata.get_object().get_data())
        removed.extend('XMP:' + name for name in xmp_removed)
    result = {'status': 'unchanged', 'before_sha256': before_hash, 'after_sha256': before_hash,
              'removed_fields': removed, 'images_reencoded': False}
    if not removed:
        return result
    baseline = semantic_snapshot(reader)
    writer = PdfWriter(clone_from=reader)
    writer.pdf_header = reader.pdf_header
    if writer._info is not None:
        for key in INFO_FIELDS:
            writer._info.pop(NameObject(key), None)
    if xmp_removed:
        stream = writer.root_object['/Metadata'].get_object()
        # Rewrite only the XML metadata stream. Image/content streams are never
        # passed through set_data(), compress_content_streams(), or optimizers.
        stream.pop(NameObject('/Filter'), None)
        stream.pop(NameObject('/DecodeParms'), None)
        stream._data = cleaned_xmp
        if hasattr(stream, 'decoded_self'):
            stream.decoded_self = None
    temporary = run_dir / ('.metadata-' + uuid.uuid4().hex + '.pdf')
    raw = run_dir / 'raw-compiled.pdf'
    try:
        with temporary.open('xb') as output:
            writer.write(output)
            output.flush()
            os.fsync(output.fileno())
        candidate = PdfReader(temporary, strict=True)
        candidate_info = candidate.trailer.get('/Info')
        candidate_info = candidate_info.get_object() if candidate_info is not None else {}
        if any(key in candidate_info for key in INFO_FIELDS):
            raise ValueError('Generator identity remained in PDF Info.')
        candidate_xmp = candidate.trailer['/Root'].get('/Metadata')
        if candidate_xmp is not None and clean_xmp(candidate_xmp.get_object().get_data())[1]:
            raise ValueError('Generator identity remained in XMP.')
        after = semantic_snapshot(candidate)
        if baseline != after:
            raise ValueError('Metadata preparation changed protected document semantics, pages, text, or encoded images.')
        if file_hash(path) != before_hash:
            raise ValueError('Compiled PDF changed during metadata preparation.')
        with path.open('rb') as original, raw.open('xb') as backup:
            shutil.copyfileobj(original, backup)
            backup.flush()
            os.fsync(backup.fileno())
        if file_hash(raw) != before_hash or file_hash(path) != before_hash:
            raise ValueError('Raw compiled PDF backup verification failed.')
        after_hash = file_hash(temporary)
        os.replace(temporary, path)
        result.update(status='prepared', after_sha256=after_hash, raw_compiled_path=str(raw),
                      raw_compiled_sha256=before_hash, preservation_check=after)
        return result
    finally:
        temporary.unlink(missing_ok=True)
