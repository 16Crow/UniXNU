#!/usr/bin/env python3
"""Build a UniXNU Data seed (DBRDISK1) from the public iPadOS IPSW, on macOS.

Why this exists
---------------
The UniXNU Data seed is a packed APFS container (DBRDISK1) that carries the
writable /private/var volume.  The upstream author keeps the real one out of
the repositories (CONTRIBUTING.md: "Do not commit ... Data seeds ..."), and
docs/devices/umi.md states plainly that the inputs are "not distributed".
So the seed has to be produced locally.

The upstream project already ships the recipe in pieces:

  * scripts/prepare-owner-data-fixture.py creates a 32 MiB APFS container and
    copies the original private/var tree from the IPSW OS volume into it.
  * drivers/DarwinBoot/Test/packed_ramdisk.py packs a raw APFS container into
    the DBRDISK1 format the payload step expects.
  * scripts/seed-data-skip-setup.py marks Setup as done on a copy.

This script joins them and fixes the one thing the upstream helper leaves to
chance: the APFS *volume UUID*.  The sheng kernel selects the Data volume by
UUID, and that UUID is compiled into the kernel as
CONFIG_XNU_OWNER_DATA_VOLUME_UUID="18AB5557-DC2D-469B-8758-855E60F5B0DF"
(configs/sheng_defconfig).  A container made with plain "hdiutil create -fs
APFS" gets a random UUID, and the kernel would then not find the volume.
macOS "newfs_apfs -u <uuid>" lets us set it exactly.

Usage (on a macOS machine, or on the GitHub macOS runner):

  # 1. get the OS disk image out of the IPSW (the build driver does this):
  ./unixnu ipsw fetch
  #    -> out/ipsw/21H461/044-76040-038.dmg
  # 2. make the seed:
  python3 make-data-seed.py \
      --os-dmg out/ipsw/21H461/044-76040-038.dmg \
      --output data.dbr

  # 3. (optional) mark Setup as done and grow the container to the tablet:
  python3 scripts/seed-data-skip-setup.py data.dbr data-setup.dbr
  python3 scripts/seed-data-grow.py --auto data.dbr data-grow.dbr

Then:
  ./unixnu build payload --unique-chip-id <hex> --trust-cache <bundle> \
      --data-ramdisk data.dbr [--skip-setup]

The script needs macOS only: hdiutil, diskutil and newfs_apfs.
"""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# The UUID the sheng kernel looks for.  It is the value of
# CONFIG_XNU_OWNER_DATA_VOLUME_UUID in configs/sheng_defconfig.
DATA_VOLUME_UUID = '18AB5557-DC2D-469B-8758-855E60F5B0DF'
VOLUME_NAME = 'OwnerData'
# Directories the Data volume must have even when the original tree is thin.
EXTRA_DIRECTORIES = ('keybags', 'keybags/backup', 'mobile/tmp', 'tmp', 'run')
# staged_system_apps is a staging area of the original OS volume, not Data state.
SKIP_DIRECTORIES = ('staged_system_apps',)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def attach_plist(*args):
    out = subprocess.check_output(list(args))
    return plistlib.loads(out)


def copy_tree(source, destination):
    """Copy private/var into the Data volume, keeping symlinks and modes."""
    files = 0
    total = 0
    for current, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRECTORIES]
        relative = Path(current).relative_to(source)
        target_root = destination / relative
        target_root.mkdir(exist_ok=True)
        os.chmod(target_root, stat.S_IMODE(Path(current).stat().st_mode))
        for name in list(dirs) + names:
            src = Path(current) / name
            dst = target_root / name
            if src.is_symlink():
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                os.symlink(os.readlink(src), dst)
                if name in dirs:
                    dirs.remove(name)
            elif src.is_file():
                shutil.copy2(src, dst)
                files += 1
                total += src.stat().st_size
    return files, total


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--os-dmg', type=Path, required=True,
                        help='The OS disk image from the IPSW (044-76040-038.dmg)')
    parser.add_argument('--output', type=Path, required=True, help='The DBRDISK1 seed to write')
    parser.add_argument('--packed-ramdisk', type=Path,
                        help='Path to drivers/DarwinBoot/Test/packed_ramdisk.py')
    parser.add_argument('--size-mib', type=int, default=64,
                        help='Raw container size in MiB (default 64; grow it later with seed-data-grow.py)')
    parser.add_argument('--uuid', default=DATA_VOLUME_UUID,
                        help='APFS volume UUID (default: the one the sheng kernel selects)')
    args = parser.parse_args()

    if sys.platform != 'darwin':
        raise SystemExit('This script needs macOS: hdiutil, diskutil and newfs_apfs.')

    os_dmg = args.os_dmg.resolve()
    if not os_dmg.is_file():
        raise SystemExit(f'OS disk image not found: {os_dmg}')
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f'Refuse to overwrite {output}')

    ramdisk = args.packed_ramdisk
    if ramdisk is None:
        ramdisk = Path(__file__).resolve().parent / 'drivers' / 'DarwinBoot' / 'Test' / 'packed_ramdisk.py'
        if not ramdisk.is_file():
            raise SystemExit('Pass --packed-ramdisk with the path to packed_ramdisk.py')
    sys.path.insert(0, str(ramdisk.resolve().parent))
    import packed_ramdisk

    size = args.size_mib * 1024 * 1024
    if size % 4096:
        raise SystemExit('The container size must be a multiple of 4096')

    with tempfile.TemporaryDirectory(prefix='unixnu-data-seed-') as scratch:
        scratch = Path(scratch)
        os_mount = scratch / 'os-mount'
        os_mount.mkdir()
        seed_mount = scratch / 'seed-mount'
        seed_mount.mkdir()
        raw = scratch / 'seed.raw'

        # 1. Mount the original OS volume read-only to read its private/var.
        attached = attach_plist('hdiutil', 'attach', '-readonly', '-nobrowse', '-owners', 'off',
                                '-mountpoint', str(os_mount), '-plist', str(os_dmg))
        os_device = attached['system-entities'][0]['dev-entry']
        try:
            var = os_mount / 'private' / 'var'
            if not var.is_dir():
                raise SystemExit(f'{os_mount} has no private/var; wrong disk image?')
            print(f'mounted the original OS volume from {os_dmg.name}')

            # 2. A raw container we can format with a chosen UUID.
            with raw.open('wb') as handle:
                handle.truncate(size)
            store = attach_plist('hdiutil', 'attach', '-imagekey',
                                 'diskimage-class=CRawDiskImage', '-nomount', '-nobrowse',
                                 '-plist', str(raw))
            store_device = store['system-entities'][0]['dev-entry']
            try:
                # 3. Format it as APFS with the exact volume UUID the kernel wants.
                run('newfs_apfs', '-v', VOLUME_NAME, '-u', args.uuid,
                    f'/dev/rdev{store_device.split("/")[-1]}')
                info = attach_plist('diskutil', 'info', '-plist', store_device)
                print(f'APFS volume {info.get("VolumeName")} uuid {info.get("VolumeUUID")}')
                if str(info.get('VolumeUUID', '')).upper() != args.uuid.upper():
                    raise SystemExit(f'the volume UUID is {info.get("VolumeUUID")}, expected {args.uuid}')

                # 4. Mount the new volume and fill it with the original var tree.
                listing = attach_plist('diskutil', 'apfs', 'list', '-plist')
                store_id = store_device.split('/')[-1]
                container_ref = None
                for container in listing.get('Containers', []):
                    for physical in container.get('PhysicalStores', []):
                        if physical.get('DeviceIdentifier') == store_id:
                            container_ref = container.get('ContainerReference')
                if not container_ref:
                    raise SystemExit('no APFS container was found on the attached seed')
                volume_device = None
                for volume in listing.get('Volumes', []):
                    if volume.get('ContainerReference') == container_ref:
                        volume_device = volume.get('DeviceIdentifier')
                if not volume_device:
                    raise SystemExit('the new APFS volume was not found')
                run('diskutil', 'mount', '-mountPoint', str(seed_mount), volume_device)
                try:
                    files, copied = copy_tree(var, seed_mount)
                    for name in EXTRA_DIRECTORIES:
                        (seed_mount / name).mkdir(parents=True, exist_ok=True)
                    os.chmod(seed_mount / 'tmp', 0o1777)
                    print(f'copied {files} files ({copied} bytes) of private/var')
                finally:
                    subprocess.run(['diskutil', 'unmount', volume_device], capture_output=True)
            finally:
                subprocess.run(['hdiutil', 'detach', store_device, '-force'],
                               capture_output=True)
        finally:
            subprocess.run(['hdiutil', 'detach', os_device, '-force'], capture_output=True)

        # 5. Pack the raw container into the DBRDISK1 format the payload wants.
        metadata = packed_ramdisk.pack(raw, output)

    report = {
        'output': str(output),
        'bytes': output.stat().st_size,
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'volume_uuid': args.uuid,
        'packed': metadata,
        'source': os_dmg.name,
        'seed_made_by': 'make-data-seed.py (from the public IPSW, not from the author)',
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
