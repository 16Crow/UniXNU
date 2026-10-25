#!/usr/bin/env python3
"""只给现有 Data 种子补齐上游显示偏好，保留 APFS 卷 UUID。"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'drivers/DarwinBoot/Test'))
import packed_ramdisk


def disk_info(path):
    # 使用真实挂载卷确认 UUID，不能用外层归档哈希代替卷身份。
    return plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(path)]))


def main():
    # 大种子只展开稀疏区间，避免读取或分配整个 200GiB 文件。
    base, output = map(lambda value: Path(value).resolve(), sys.argv[1:3])
    expected_uuid = sys.argv[3].upper()
    if output.exists() or os.geteuid() != 0:
        raise RuntimeError('Requires a new output path and root for correct iOS preference ownership')
    blob = base.read_bytes()
    logical, extents = packed_ramdisk.regions(blob)
    changes = []
    with tempfile.TemporaryDirectory(prefix='sheng-display-prefs-') as folder:
        folder = Path(folder)
        raw, mount = folder / 'seed.raw', folder / 'mount'
        with raw.open('wb') as handle:
            handle.truncate(logical)
            for offset, data in extents:
                handle.seek(offset)
                handle.write(data)
        mount.mkdir()
        attached = plistlib.loads(subprocess.check_output([
            'hdiutil', 'attach', '-imagekey', 'diskimage-class=CRawDiskImage',
            '-nobrowse', '-owners', 'on', '-mountpoint', str(mount), '-plist', str(raw)]))
        devices = [entry['dev-entry'] for entry in attached['system-entities'] if entry.get('dev-entry')]
        device = devices[0]
        try:
            before_uuid = disk_info(mount).get('VolumeUUID', '').upper()
            if before_uuid != expected_uuid or not (mount / 'mobile').is_dir():
                raise RuntimeError(f'Unexpected Data volume UUID: {before_uuid}')
            graphics = {'CAEnableDeepFramebuffer': False, 'CAEnableFramebufferCompression': False,
                        'CAEnableIOSurfaceCompression': False}
            awake = {'SBDisableAutoDim': True, 'SBDontDimOrLockOnAC': True, 'SBDisableIdleSleep': True}
            for home, uid in (('mobile', 501), ('root', 0)):
                directory = mount / home / 'Library/Preferences'
                directory.mkdir(parents=True, exist_ok=True)
                os.chown(directory, uid, uid)
                for name, settings in (('backboardd.plist', graphics), ('.GlobalPreferences.plist', graphics),
                                       ('com.apple.springboard.plist', awake)):
                    # 与上游 add-gpu-plugin-data / skip-setup 的偏好一致，只合并指定键。
                    path = directory / name
                    previous = plistlib.loads(path.read_bytes()) if path.exists() else {}
                    merged = dict(previous, **settings)
                    path.write_bytes(plistlib.dumps(merged, fmt=plistlib.FMT_BINARY))
                    os.chown(path, uid, uid)
                    os.chmod(path, 0o644)
                    observed = plistlib.loads(path.read_bytes())
                    if observed != merged or any(observed[key] != value for key, value in previous.items() if key not in settings):
                        raise RuntimeError('Preference merge verification failed')
                    changes.append({'path': str(path.relative_to(mount)), 'settings': settings, 'uid': uid})
            if disk_info(mount).get('VolumeUUID', '').upper() != before_uuid:
                raise RuntimeError('Volume UUID changed')
        finally:
            subprocess.run(['hdiutil', 'detach', device], check=True)
        with raw.open('rb') as handle:
            handle.seek(32)
            if handle.read(4) != b'NXSB':
                raise RuntimeError('APFS container header was lost')
        metadata = packed_ramdisk.pack(raw, output)
    report = {'source_sha256': hashlib.sha256(blob).hexdigest(), 'logical_bytes': logical,
              'volume_uuid': before_uuid, 'uuid_unchanged': True, 'changes': changes,
              'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'packed': metadata}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
