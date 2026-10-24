#!/usr/bin/env python3
"""把目标 IPSW 的两个原始信任模块合并为板级允许的缓存。"""
import hashlib
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

from unixnu.config import Context
from unixnu.ipsw import Ipsw, im4p_payload


def prepare(output):
    # 复用构建器的设备身份检查和 IPSW 缓存，不使用外部未知信任模块。
    context = Context(SimpleNamespace(device=None, out=None, jobs=None))
    source = Ipsw(context)
    modules = []
    for name in ('StaticTrustCache', 'Cryptex1,SystemTrustCache'):
        module = im4p_payload(source.extract(name).read_bytes())
        if len(module) < 24:
            raise SystemExit('Truncated trust module: ' + name)
        version, = struct.unpack_from('<I', module)
        count, = struct.unpack_from('<I', module, 20)
        if version != 2 or len(module) != 24 + count * 24:
            raise SystemExit('Unexpected original trust module layout: ' + name)
        modules.append(module)
    bundle = struct.pack('<3I', 2, 12, 12 + len(modules[0])) + b''.join(modules)
    digest = hashlib.sha256(bundle).hexdigest()
    if digest != '7416ca4f8377146626bb284e2133c76bee6cb4e3ee0af5d648b186235a7323a7':
        raise SystemExit('Original trust bundle differs from the pinned target')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bundle)
    # 保留官方 GPU 插件工具所需的原始模块输入。
    original = context.tree / 'build/original-static-system-trust/original-static-system.bundle'
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(bundle)
    print('Prepared unchanged original trust bundle: ' + digest)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
