#!/usr/bin/env python3
"""用真实 IPSW 卷生成完整 sheng 内核所需的 owner 策略和验证归档。"""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, **options):
    # 任一步实际签名或验证失败都停止，不能留下“已验证”的假报告。
    return subprocess.run([str(value) for value in command], cwd=cwd, check=True, **options)


def attach(image, mountpoint):
    # 只挂载明确指定的磁盘映像，不触碰主机物理磁盘。
    mountpoint.mkdir(parents=True, exist_ok=True)
    result = run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-plist',
                  '-mountpoint', mountpoint, image], ROOT, capture_output=True)
    entities = plistlib.loads(result.stdout)['system-entities']
    whole = [entry['dev-entry'] for entry in entities
             if entry.get('dev-entry') and entry.get('content-hint') == 'GUID_partition_scheme']
    if not whole:
        whole = [entry['dev-entry'] for entry in entities if entry.get('dev-entry')]
    if not whole:
        raise RuntimeError('No attached virtual disk device')
    return whole[0]


def main():
    # 生成本轮构建专用密钥，两份原始卷策略使用同一公钥。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    args = parser.parse_args()
    tree = args.tree.resolve()
    host = tree / 'build/verified-root-host'
    keys = host / 'keys'
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(keys, 0o700)
    private, public = keys / 'owner.pem', keys / 'owner-public.pem'
    if not private.exists():
        fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072',
             '-out', private], tree, capture_output=True)
    run(['openssl', 'pkey', '-in', private, '-pubout', '-out', public], tree, capture_output=True)
    prefix = subprocess.check_output(['brew', '--prefix', 'openssl@3'], text=True).strip()
    kit = tree / 'kits/VerifiedRoot'
    run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
         '-I', kit / 'include', '-I', Path(prefix) / 'include', kit / 'src/verified_root.c',
         kit / 'tests/openssl_provider.c', '-L', Path(prefix) / 'lib', '-lcrypto',
         '-o', host / 'verified-root.dylib'], tree)

    run([ROOT / 'unixnu', 'ipsw', 'fetch', 'OS', 'Cryptex1,SystemOS'], ROOT)
    volumes = tree / '.cache/firmware/target-volumes'
    volumes.mkdir(parents=True, exist_ok=True)
    for name in ('044-76040-038.dmg', '044-76034-038.dmg'):
        found = list((ROOT / 'out/ipsw').glob('*/' + name))
        if len(found) != 1:
            raise RuntimeError('Expected one verified IPSW member: ' + name)
        target = volumes / name
        if not target.exists():
            target.symlink_to(found[0].resolve())
        elif target.resolve() != found[0].resolve():
            raise RuntimeError('Unexpected existing volume input: ' + name)

    os_mount = volumes / 'os-mount'
    system_mount = volumes / 'systemos-mount'
    disks = []
    try:
        disks.append(attach(volumes / '044-76040-038.dmg', os_mount))
        disks.append(attach(volumes / '044-76034-038.dmg', system_mount))
        info = plistlib.loads(run(['diskutil', 'info', '-plist', system_mount],
                                 tree, capture_output=True).stdout)
        system_uuid = '8846FE78-2910-4297-AF97-D59BB6F8FC16'
        if info.get('VolumeUUID') != system_uuid or info.get('Writable') is not False:
            raise RuntimeError('SystemOS is not the expected read-only volume')
        destination = tree / 'build/verified-root-systemos'
        run(['python3', kit / 'tools/manifest.py', '--image', volumes / '044-76034-038.dmg',
             '--private-key', private, '--public-key', public, '--volume-uuid', system_uuid,
             '--generation', '1', '--output', destination], tree)
        run(['python3', kit / 'tools/verify_image.py', '--library', host / 'verified-root.dylib',
             '--manifest', destination / 'manifest.bin', '--trusted-key', destination / 'trusted-key.bin',
             '--image', volumes / '044-76034-038.dmg', '--volume-uuid', system_uuid,
             '--minimum-generation', '1', '--output', destination / 'verification.json'], tree)
        run(['sudo', sys.executable, tree / 'scripts/build-owner-os-policy.py'], tree)
    finally:
        for disk in reversed(disks):
            subprocess.run(['hdiutil', 'detach', disk], capture_output=True)

    run(['python3', tree / 'scripts/build-verified-root-probe.py',
         '--component', 'os', '--include-systemos'], tree)
    run(['python3', tree / 'scripts/build-arm-driver.py', 'NativeVirtioBlock',
         '--verified-root', '--verified-root-bundle'], tree)
    run(['python3', tree / 'scripts/build-native-virtio-bindings.py',
         '--component', 'NativeVirtioBlock', '--directory', 'build/native-virtio-block-verified-bundle'], tree)
    print('Prepared genuinely signed and fully verified OS/SystemOS policy archives')


if __name__ == '__main__':
    main()
