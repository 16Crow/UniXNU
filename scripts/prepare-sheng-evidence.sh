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

# 最小候选只用于打破“先有归档还是先有运行证据”的构建循环。
printf '%s\n' 'CONFIG_XNU_CRYPTO_BOOTSTRAP="prelinked"' > "$UNIXNU_DEVICE/configs/sheng_evidence_defconfig"
./unixnu defconfig sheng_evidence_defconfig
./unixnu build kernel

TREE=$ROOT/out/sheng/tree
# 无论后续停在哪一步，都把实际虚拟机日志带回官方日志目录。
collect_probe_logs() {
  local result=$?
  if [ -d "$TREE/build/darwinboot-storage-native-metadata" ]; then
    while IFS= read -r path; do
      cp "$path" "$ROOT/out/sheng/logs/$(basename "$path")" || true
    done < <(find "$TREE/build/darwinboot-storage-native-metadata" -maxdepth 1 -name '*.log' -type f)
  fi
  exit "$result"
}
trap collect_probe_logs EXIT
CANDIDATES=$TREE/build/native-prelink
mkdir -p "$CANDIDATES"
for name in native-apfs-load-positive native-defaults-candidate native-owner-mobile-graphics-candidate native-owner-ufs-cpu-desktop-v9-hid-init-candidate; do
  cp out/sheng/kernel/kernel.macho "$CANDIDATES/$name.macho"
  cp out/sheng/kernel/kernel.json "$CANDIDATES/$name.json"
done
rm out/sheng/kernel/kernel.macho out/sheng/kernel/kernel.json

# 保持 PMGR 等旧工具读取的原版缓存与 board.toml 校验过的输入一致。
ORIGINAL=$(./unixnu ipsw fetch KernelCache | tail -n 1)
test -s "$ORIGINAL"
mkdir -p "$TREE/.cache/firmware/kernelcache.macho"
cp "$ORIGINAL" "$TREE/.cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed"

./unixnu build package

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
           '--break-symbol', '_bsd_init', '--timeout', '120']
for request in plan['read_memory']:
    command += ['--read-memory', request]
subprocess.run(command, check=True)
PY

# 此步仍检查真实元类、父类、MMU 状态和候选哈希，超时不能算通过。
python3 scripts/audit-storage-interface.py \
  2>&1 | tee "$ROOT/out/sheng/logs/storage-interface-audit.log"
