#!/usr/bin/env bash
# 补齐官方审计的前置候选与真实 UEFI 环境；不改完整系统的验证规则。
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

# 本轮只能采集证据，禁止后续步骤把最小候选包装成完整系统。
if [ "${STEPS:-kernel}" != kernel ]; then
  echo 'Evidence preparation requires steps=kernel; full payloads need a separate verified build.' >&2
  exit 1
fi

# QEMU 采集使用实际虚拟硬件平台驱动，避免由原版平台驱动访问板级 MMIO。
# 这里只准备审计运行环境；完整 sheng 配置和归档清单随后保持原样。
mkdir -p "$ROOT/out/sheng"
cp "$UNIXNU_DEVICE/board.toml" "$ROOT/out/sheng/evidence-board.toml"
python3 - "$UNIXNU_DEVICE" <<'PY'
import json
from pathlib import Path
import re
import sys

device = Path(sys.argv[1])
board = device / 'board.toml'
entries = ['build-corecrypto-14.py', 'build-corecrypto-14.py --namespace',
           'build-arm-driver.py ArmDTPlatform', 'build-arm-driver.py ArmCpu',
           'build-libpthread-kernel.py']
text, count = re.subn(r'(?ms)^archives = \[.*?^\]',
                     'archives = ' + json.dumps(entries, indent=2), board.read_text())
if count != 1:
    raise SystemExit('Cannot select the explicit QEMU archive chain')
board.write_text(text)
names = ('BUILD_ARCHIVES', 'SOURCE_CORECRYPTO14', 'SOURCE_PTHREAD',
         'ARM_DT_PLATFORM', 'ARMCPU', 'TRUST_CACHE_RUNTIME', 'NATIVE_ARCH_TIMER')
config = '\n'.join('CONFIG_XNU_' + name + '=y' for name in names)
(device / 'configs/sheng_qemu_evidence_defconfig').write_text(
    config + '\nCONFIG_XNU_CRYPTO_BOOTSTRAP="prelinked"\n')
PY
./unixnu defconfig sheng_qemu_evidence_defconfig
./unixnu build kernel
cp "$ROOT/out/sheng/evidence-board.toml" "$UNIXNU_DEVICE/board.toml"

TREE=$ROOT/out/sheng/tree
# 无论后续停在哪一步，都把实际虚拟机日志带回官方日志目录。
collect_probe_logs() {
  local result=$?
  if [ -d "$TREE/build/darwinboot-storage-native-metadata" ]; then
    while IFS= read -r path; do
      cp "$path" "$ROOT/out/sheng/logs/$(basename "$path")" || true
    done < <(find "$TREE/build/darwinboot-storage-native-metadata" -maxdepth 1 -name '*.log' -type f)
    if [ -f "$TREE/build/darwinboot-storage-native-metadata/gdb-stop.json" ]; then
      cp "$TREE/build/darwinboot-storage-native-metadata/gdb-stop.json" "$ROOT/out/sheng/logs/qemu-storage-snapshot.log" || true
      python3 - "$CANDIDATES/native-apfs-load-positive.json" "$TREE/build/darwinboot-storage-native-metadata/gdb-stop.json" > "$ROOT/out/sheng/logs/qemu-fault-context.log" <<'PY_DIAG' || true
import json, sys
plan = json.load(open(sys.argv[1]))
state = json.load(open(sys.argv[2]))
addresses = [state.get('kernel_exception', {}).get('pc', state['pc'])]
addresses += [frame['lr'] for frame in state.get('frame_chain', [])]
for value in addresses:
    address = int(value, 16)
    matches = [dict(module=e['module'], segment=e['segment'], offset=hex(address-e['va']))
               for e in plan['extents'] if e['va'] <= address < e['va'] + e['size']]
    print(value, json.dumps(matches))
PY_DIAG
    fi
  fi
  exit "$result"
}
trap collect_probe_logs EXIT
CANDIDATES=$TREE/build/native-prelink
mkdir -p "$CANDIDATES"

# 保持 PMGR 等旧工具读取的原版缓存与 board.toml 校验过的输入一致。
ORIGINAL=$(./unixnu ipsw fetch KernelCache | tail -n 1)
test -s "$ORIGINAL"
mkdir -p "$TREE/.cache/firmware/kernelcache.macho"
cp "$ORIGINAL" "$TREE/.cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed"

./unixnu build package
# package 会重组源码引用；prelink 恢复 kernel 的引用，不重复编译 XNU。
./unixnu build prelink
for name in native-apfs-load-positive native-defaults-candidate native-owner-mobile-graphics-candidate native-owner-ufs-cpu-desktop-v9-hid-init-candidate; do
  cp out/sheng/kernel/kernel.macho "$CANDIDATES/$name.macho"
  cp out/sheng/kernel/kernel.json "$CANDIDATES/$name.json"
done
rm out/sheng/kernel/kernel.macho out/sheng/kernel/kernel.json

# 当前 CLI 与旧调试工具的目录不同，只映射真实产物，不伪造报告。
EDK2=$(find "$ROOT/out/feeds" -maxdepth 1 -type d -name 'mu_basecore-*' -print -quit)
test -n "$EDK2"
test -f "$EDK2/MdePkg/MdePkg.dec"
ln -s "$EDK2" "$TREE/package/Mu_Basecore"
mkdir -p "$TREE/package/Build" "$TREE/unixnu/Build"
cp -R "$ROOT/out/sheng/package/Build/Conf" "$TREE/package/Build/Conf"
ln -s "$ROOT/out/sheng/package/Build/Out" "$TREE/unixnu/Build/Out"

export PATH="$(brew --prefix llvm)/bin:$(brew --prefix lld)/bin:$PATH"
export CLANG_BIN="$ROOT/out/sheng/toolchain/"
cd "$TREE"
bash scripts/build-darwinboot.sh 2>&1 | tee "$ROOT/out/sheng/logs/darwinboot-build.log"

# 先从真实候选和本次编译对象计算采集地址，避免硬编码或伪造内存。
python3 scripts/audit-storage-interface.py --prepare-snapshot \
  2>&1 | tee "$ROOT/out/sheng/logs/storage-snapshot-plan.log"
python3 - "$CANDIDATES/native-apfs-load-positive.macho" <<'PY' \
  2>&1 | tee "$ROOT/out/sheng/logs/qemu-storage-preflight.log"
import json
from pathlib import Path
import subprocess
import sys

plan = json.loads(Path('build/storage-abi/snapshot-plan.json').read_text())
command = ['python3', 'scripts/probe-darwinboot-xnu.py', '--kernel', sys.argv[1],
           '--output', 'build/darwinboot-storage-native-metadata',
           '--break-symbol', '_bsd_init', '--timeout', '120',
           '--armvirt', '--armdt-platform', '--qemu-vmm-present', '--armcpu',
           '--nvram-proxy', '--crypto-hash-method', 'sha2-384', '--amfi-platform-only']
for request in plan['read_memory']:
    command += ['--read-memory', request]
subprocess.run(command, check=True)
PY

# 此步仍检查真实元类、父类、MMU 状态和候选哈希，超时不能算通过。
python3 scripts/audit-storage-interface.py \
  2>&1 | tee "$ROOT/out/sheng/logs/storage-interface-audit.log"

# 存储证据通过后继续补齐完整显示链和两个原始卷的验证策略。
bash scripts/capture-sheng-display.sh "$ROOT/out/sheng/logs"
cd "$ROOT"
python3 scripts/prepare-sheng-policies.py --tree "$TREE" \
  2>&1 | tee "$ROOT/out/sheng/logs/verified-root-policies.log"
