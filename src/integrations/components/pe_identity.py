# 只读解析 PE 导出名称以区分第三方代理，不加载或执行待识别 DLL。
from __future__ import annotations

from pathlib import Path
import mmap
import struct


def exported_names(path: Path) -> frozenset[str]:
    """名称只用于避免误覆盖，不代表签名可信或运行时能力已经验证。"""
    try:
        with path.open('rb') as stream:
            if stream.seek(0, 2) == 0:
                return frozenset()
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
                return _names(image)
    except FileNotFoundError:
        return frozenset()
    except (ValueError, struct.error, UnicodeDecodeError):
        return frozenset()


def _names(image) -> frozenset[str]:
    def read(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(image):
            raise ValueError('PE field outside file')
        return struct.unpack_from(fmt, image, offset)

    if image[:2] != b'MZ':
        return frozenset()
    pe, = read('<I', 0x3C)
    if image[pe:pe + 4] != b'PE\0\0':
        return frozenset()
    machine, sections = read('<HH', pe + 4)
    optional_size, = read('<H', pe + 20)
    optional = pe + 24
    magic, = read('<H', optional)
    if machine != 0x8664 or magic != 0x20B or not 0 < sections <= 96 or optional_size < 120:
        return frozenset()
    directories, = read('<I', optional + 108)
    if not directories:
        return frozenset()
    export_rva, export_size = read('<II', optional + 112)
    if not export_rva or export_size < 40:
        return frozenset()
    headers, = read('<I', optional + 60)
    spans = []
    for index in range(sections):
        offset = optional + optional_size + index * 40
        _, rva, raw_size, raw = read('<IIII', offset + 8)
        spans.append((rva, raw_size, raw))

    def locate(rva, size):
        if rva < headers and rva + size <= min(headers, len(image)):
            return rva
        matches = [raw + rva - start for start, length, raw in spans
                   if start <= rva and rva + size <= start + length
                   and raw + rva - start + size <= len(image)]
        if len(matches) != 1:
            raise ValueError('PE RVA is ambiguous or outside raw data')
        return matches[0]

    exports = locate(export_rva, 40)
    count, = read('<I', exports + 24)
    names_rva, = read('<I', exports + 32)
    if count > 65536:
        raise ValueError('PE export count exceeds inspection bound')
    table = locate(names_rva, count * 4)
    result = set()
    for index in range(count):
        name_rva, = read('<I', table + index * 4)
        name = bytearray()
        for position in range(256):
            value = image[locate(name_rva + position, 1)]
            if not value:
                result.add(name.decode('ascii'))
                break
            name.append(value)
        else:
            raise ValueError('PE export name exceeds inspection bound')
    return frozenset(result)


def is_reshade(path: Path) -> bool:
    return 'ReShadeVersion' in exported_names(path)
