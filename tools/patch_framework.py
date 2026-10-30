"""Patch the existing framework dimension; sign the output before deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--expected-sha256', required=True)
args = parser.parse_args()
assert not args.output.exists(), 'Refusing to overwrite an output APK'
assert hashlib.sha256(args.source.read_bytes()).hexdigest() == args.expected_sha256

with zipfile.ZipFile(args.source) as source:
    original = source.read('resources.arsc')
    data = bytearray(original)

    def u16(offset):
        return struct.unpack_from('<H', data, offset)[0]

    def u32(offset):
        return struct.unpack_from('<I', data, offset)[0]

    def strings(offset):
        assert u16(offset) == 1
        count, flags = u32(offset + 8), u32(offset + 16)
        start, offsets = offset + u32(offset + 20), offset + u16(offset + 2)

        def length(position, utf8):
            value = data[position] if utf8 else u16(position)
            if utf8:
                return (((value & 127) << 8) | data[position + 1], position + 2) if value & 128 else (value, position + 1)
            return (((value & 32767) << 16) | u16(position + 2), position + 4) if value & 32768 else (value, position + 2)

        result = []
        for index in range(count):
            position = start + u32(offsets + index * 4)
            if flags & 256:
                _, position = length(position, True)
                size, position = length(position, True)
                result.append(data[position:position + size].decode('utf-8'))
            else:
                size, position = length(position, False)
                result.append(data[position:position + size * 2].decode('utf-16-le'))
        return result

    patches = []
    position = u16(2)
    while position < len(data):
        kind, header, size = struct.unpack_from('<HHI', data, position)
        assert size >= header > 0 and position + size <= len(data)
        if kind == 0x200:
            assert u32(position + 8) == 1, 'Expected the android resource package'
            types = strings(position + u32(position + 268))
            keys = strings(position + u32(position + 276))
            chunk = position + header
            while chunk < position + size:
                chunk_kind, chunk_header, chunk_size = struct.unpack_from('<HHI', data, chunk)
                assert chunk_size >= chunk_header > 0
                if chunk_kind == 0x201 and types[data[chunk + 8] - 1] == 'dimen':
                    count, entries = u32(chunk + 12), u32(chunk + 16)
                    for index in range(count):
                        offset = u32(chunk + chunk_header + index * 4)
                        if offset == 0xffffffff:
                            continue
                        entry = chunk + entries + offset
                        if keys[u32(entry + 4)] != 'status_bar_height':
                            continue
                        assert not u16(entry + 2) & 1
                        value = entry + u16(entry)
                        assert data[value + 3] == 5 and u32(value + 4) == 1, 'Expected 0dp'
                        struct.pack_into('<I', data, value + 4, 0x1801)
                        patches.append({'resource': 'android:dimen/status_bar_height', 'offset': value + 4, 'before': '0dp', 'after': '24dp'})
                chunk += chunk_size
        position += size
    assert len(patches) == 1, 'Expected exactly one status-bar dimension'
    allowed = set(range(patches[0]['offset'], patches[0]['offset'] + 4))
    assert all(a == b or index in allowed for index, (a, b) in enumerate(zip(original, data)))

    with zipfile.ZipFile(args.output, 'x') as output:
        for info in source.infolist():
            name = info.filename.upper()
            if name == 'META-INF/MANIFEST.MF' or (name.startswith('META-INF/') and name.endswith(('.SF', '.RSA', '.DSA', '.EC'))):
                continue
            output.writestr(info, data if info.filename == 'resources.arsc' else source.read(info.filename))

print(json.dumps({'source_sha256': args.expected_sha256, 'patches': patches, 'output': str(args.output)}, indent=2))
