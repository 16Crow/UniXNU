#!/usr/bin/env python3
"""准备固定版本的 Mesa 源码及构建工具，不运行编译器测试。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from mesa_patch_identity import validate_recorded_patches

parser = argparse.ArgumentParser(description=__doc__)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache'
OUT = ROOT / 'build/mesa-ir3'
pins = json.loads((ROOT / 'scripts/data/adreno-compiler-inputs.json').read_text())
source = CACHE / 'mesa-work'
venv = CACHE / 'mesa-venv'
tools = CACHE / 'mesa-tools'


def run(command, *, cwd=ROOT, log=None, timeout=60, env=None):
    # 执行构建命令，失败时只显示日志末尾。
    command = [str(x) for x in command]
    if log:
        with (CACHE / log).open('w') as stream:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            raise RuntimeError(log + ':\n' + '\n'.join((CACHE / log).read_text().splitlines()[-20:]))
        return ''
    return subprocess.check_output(command, cwd=cwd, env=env, text=True, timeout=timeout).strip()


CACHE.mkdir(exist_ok=True)
if not (source / '.git').exists():
    run(['git', 'init', source])
    run(['git', '-C', source, 'remote', 'add', 'origin', pins['mesa']['mirror']])
    run(['git', '-C', source, 'fetch', '--depth=1', '--filter=blob:none', 'origin', pins['mesa']['commit']], timeout=180)
    run(['git', '-C', source, 'sparse-checkout', 'init', '--cone'])
    run(['git', '-C', source, 'sparse-checkout', 'set', *pins['mesa']['sparse_directories']])
    run(['git', '-C', source, 'checkout', '--detach', 'FETCH_HEAD'], timeout=180)
if run(['git', '-C', source, 'rev-parse', 'HEAD']) != pins['mesa']['commit'] or \
        run(['git', '-C', source, 'rev-parse', 'HEAD^{tree}']) != pins['mesa']['tree']:
    raise SystemExit('Pinned Mesa commit/tree differs')
# A pristine checkout can receive the whole sequence once. Existing work must
# equal all recorded patches; verify overlapping patches on a temporary copy.
clean = subprocess.run(['git', '-C', source, 'diff', '--quiet', 'HEAD'], capture_output=True).returncode == 0
extras = run(['git', '-C', source, 'ls-files', '--others', '--exclude-standard'])
if clean and not extras:
    for name in pins['patches']:
        run(['git', '-C', source, 'apply', ROOT / name])
validate_recorded_patches(ROOT, source, pins)

if not (venv / 'bin/python').exists():
    run([sys.executable, '-m', 'venv', venv])
requirements = (ROOT / 'scripts/requirements-adreno-compiler.txt').read_text().splitlines()
expected_packages = {line.split('==')[0].lower(): line.split('==')[1] for line in requirements if line.strip()}
installed = json.loads(run([venv / 'bin/python', '-c', 'import importlib.metadata,json; print(json.dumps({d.metadata["Name"].lower():d.version for d in importlib.metadata.distributions()}))']))
if any(installed.get(name) != version for name, version in expected_packages.items()):
    run([venv / 'bin/pip', 'install', '-r', ROOT / 'scripts/requirements-adreno-compiler.txt'],
        log='mesa-python-install.log', timeout=180)

bison = tools / 'bin/bison'
if not bison.exists() or run([bison, '--version']).splitlines()[0] != 'bison (GNU Bison) 3.8.2':
    archive = CACHE / 'tool-sources/bison-3.8.2.tar.xz'
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(pins['bison']['url'], timeout=30) as stream:
            archive.write_bytes(stream.read(pins['bison']['bytes'] + 1))
    data = archive.read_bytes()
    if len(data) != pins['bison']['bytes'] or hashlib.sha256(data).hexdigest() != pins['bison']['sha256']:
        raise SystemExit('GNU Bison release input differs')
    tool_source = archive.parent / 'bison-3.8.2'
    if not tool_source.exists():
        with tarfile.open(archive) as stream:
            stream.extractall(archive.parent, filter='data')
    tool_build = CACHE / 'tool-build/bison'
    tool_build.mkdir(parents=True, exist_ok=True)
    run([tool_source / 'configure', '--prefix=' + str(tools), '--disable-nls'], cwd=tool_build,
        log='bison-configure.log', timeout=300)
    run(['make', '-j4'], cwd=tool_build, log='bison-build.log', timeout=300)
    run(['make', 'install'], cwd=tool_build, log='bison-install.log', timeout=60)

print('Prepared pinned Mesa source, recorded patches and compiler tools; no test suite executed')
