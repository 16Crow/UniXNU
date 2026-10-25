#!/usr/bin/env python3
"""只读提取当前系统版本的 Metal 库清单与 cryptex 库副本。"""
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from unixnu.ipsw import Ipsw


def sha(path):
    # 流式计算系统镜像校验值，避免一次读入数 GB。
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    # 固定为实机已写入的 21H461，避免混入另一系统版本的库。
    stage = Path(sys.argv[1]).resolve()
    stage.mkdir(parents=True, exist_ok=True)
    output = stage / 'prime-resources'
    output.mkdir()
    board = {'ipsw': dict(
        url='https://updates.cdn-apple.com/2025SpringFCS/fullrestores/122-77166/DCA6CFE8-90E9-4B92-880D-3DE171798E40/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw',
        product='iPad7,1', version='17.7.11', build='21H461', device_class='j120ap', chip_id=0x8011, board_id=12,
        sha256={'044-76040-038.dmg': '3f99b859c9728379110b66657c7b15285bcb1925ad8b5726542e2cdcf8b1028d',
                '044-76034-038.dmg': 'b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f'})}
    source = Ipsw(SimpleNamespace(board=board, out_root=stage, option_text=lambda *_: None))
    paths, copies, images = set(), [], []
    for component in ('OS', 'Cryptex1,SystemOS'):
        dmg = source.extract(component)
        mount = stage / ('os-mount' if component == 'OS' else 'cryptex-mount')
        mount.mkdir()
        result = subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noverify', '-plist',
                                 '-mountpoint', str(mount), str(dmg)], check=True, capture_output=True)
        entities = plistlib.loads(result.stdout)['system-entities']
        device = next(item['dev-entry'] for item in entities if 'dev-entry' in item)
        found = []
        try:
            # 沙盒能读取具体文件，但无法枚举多数目录，因此提前生成完整清单。
            for library in sorted(mount.rglob('*.metallib')):
                if not library.is_file():
                    continue
                relative = library.relative_to(mount).as_posix()
                if component == 'OS':
                    target = '/' + relative
                else:
                    # 将 cryptex 库放在插件旁，避开桌面进程无法读取 cryptex 的限制；不修改已签名 bundle。
                    name = hashlib.sha256(relative.encode()).hexdigest()[:20] + '.metallib'
                    addon = 'addons/NativeAdrenoMetal.prime/' + name
                    destination = output / addon
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(library, destination)
                    target = '/System/Library/Extensions/NativeAdrenoMetal.prime/' + name
                    copies.append(dict(source='/System/Cryptexes/OS/' + relative, addon=addon,
                                       target=target, size=destination.stat().st_size, sha256=sha(destination)))
                paths.add(target)
                found.append(relative)
        finally:
            subprocess.run(['hdiutil', 'detach', device], check=True)
        images.append(dict(component=component, member=dmg.name, sha256=sha(dmg), libraries=found))
        print(f'{component}: {len(found)} libraries', flush=True)
    if not copies or not any('QuartzCore' in item['source'] for item in copies):
        raise RuntimeError('Missing matching cryptex QuartzCore metallib')
    listing = output / 'addons/NativeAdrenoMetal.primelist'
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(''.join(path + '\n' for path in sorted(paths)))
    report = dict(build='21H461', libraries=len(paths), copies=copies, images=images,
                  primelist_sha256=sha(listing), base_addon_sha256='dfa4accbe9d16a2207e761639a0bc3f2ee1682d6c3f5c585532b0de1ef3eef16')
    (output / 'prime-resources.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
