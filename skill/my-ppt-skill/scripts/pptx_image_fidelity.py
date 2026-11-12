"""Preserve embedded media and disable automatic picture compression per deck.

Run preparation on a derived candidate before PowerPoint opens it and before
rendering/sign-off. Image size advisories never request stdin or alter media.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as ET

PRESENTATION = 'ppt/presentation.xml'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
LARGE_IMAGE_BYTES = 20_000_000


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def _parts(data):
    with ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        parts = {info.filename: archive.read(info) for info in infos}
        if len(parts) != len(infos):
            raise ValueError('Duplicate ZIP parts')
        return parts, infos, archive.comment


def media_manifest(data):
    parts, _, _ = _parts(data)
    return {name: {'bytes': len(value), 'sha256': sha(value)}
            for name, value in sorted(parts.items())
            if name.startswith('ppt/media/') and not name.endswith('/')}


def inspect(data):
    parts, _, _ = _parts(data)
    root = ET.fromstring(parts[PRESENTATION])
    if root.tag != '{' + P + '}presentation':
        raise ValueError('Unsupported presentation root')
    types = ET.fromstring(parts['[Content_Types].xml'])
    defaults = {entry.get('Extension', '').lower(): entry.get('ContentType', '')
                for entry in types if ET.QName(entry).localname == 'Default'}
    overrides = {entry.get('PartName', '').lstrip('/'): entry.get('ContentType', '')
                 for entry in types if ET.QName(entry).localname == 'Override'}
    media = media_manifest(data)
    large = [{'part': name, **details} for name, details in media.items()
             if details['bytes'] > LARGE_IMAGE_BYTES and
             overrides.get(name, defaults.get(name.rsplit('.', 1)[-1].lower(), '')).startswith('image/')]
    return {'auto_compress_pictures': root.get('autoCompressPictures'),
            'media': media, 'large_images': large,
            'large_image_threshold_bytes': LARGE_IMAGE_BYTES}


def transform(data):
    """Return a candidate whose only allowed part change is presentation XML."""
    report = inspect(data)
    if report['auto_compress_pictures'] in ('0', 'false'):
        return data, report
    parts, infos, comment = _parts(data)
    root = ET.fromstring(parts[PRESENTATION])
    root.set('autoCompressPictures', '0')
    parts[PRESENTATION] = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.comment = comment
        for info in infos:
            archive.writestr(info, parts[info.filename])
    result = output.getvalue()
    after, _, _ = _parts(result)
    before, _, _ = _parts(data)
    if set(before) != set(after) or any(before[name] != after[name]
                                        for name in before if name != PRESENTATION):
        raise ValueError('Unexpected package mutation')
    return result, inspect(result)


def verify(reference, candidate):
    """Detect removed, added, renamed, or re-encoded media after external saves."""
    errors = []
    if inspect(candidate)['auto_compress_pictures'] not in ('0', 'false'):
        errors.append('Automatic picture compression is enabled or unspecified')
    before, after = media_manifest(reference), media_manifest(candidate)
    for name in sorted(set(before) | set(after)):
        if before.get(name) != after.get(name):
            errors.append('Embedded media changed: ' + name)
    return errors


def prepare(input_path, output_path):
    """Create a separate candidate, never overwrite the source or other output."""
    source, destination = Path(input_path), Path(output_path)
    if source.resolve() == destination.resolve() or (
            destination.exists() and os.path.samefile(source, destination)):
        raise ValueError('Output must be a separate copy of the original')
    original = source.read_bytes()
    result, report = transform(original)
    if destination.exists():
        if destination.read_bytes() != result:
            raise FileExistsError('Output already exists with different content')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=destination.name + '.', suffix='.tmp', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(result)
                stream.flush()
                os.fsync(stream.fileno())
            if source.read_bytes() != original:
                raise ValueError('Source changed during preparation')
            # Publish atomically without replacing an existing destination.
            os.link(temporary, destination)
        finally:
            os.unlink(temporary)
    return {'input_sha256': sha(original), 'output_sha256': sha(result),
            'output': str(destination.resolve()), **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--input', required=True)
    prep.add_argument('--output', required=True)
    check = commands.add_parser('inspect')
    check.add_argument('--pptx', required=True)
    comparison = commands.add_parser('verify')
    comparison.add_argument('--reference', required=True)
    comparison.add_argument('--pptx', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        report = prepare(args.input, args.output)
    elif args.command == 'inspect':
        report = inspect(Path(args.pptx).read_bytes())
    else:
        errors = verify(Path(args.reference).read_bytes(), Path(args.pptx).read_bytes())
        print(json.dumps({'errors': errors}, ensure_ascii=True))
        return 2 if errors else 0
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
