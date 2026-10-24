#!/usr/bin/env bash
# 观察原版 Legacy 显示类的真实初始化，供完整显示驱动构建使用。
set -euo pipefail
TREE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOGS=$1
cd "$TREE"
OUTPUT=$TREE/build/darwinboot-owner-hvf-mobile-graphics-legacy-class

# 目录名沿用官方工具约定；本次仍运行真实 QEMU TCG，不冒充硬件验证。
collect_display_logs() {
  local result=$?
  if [ -d "$OUTPUT" ]; then
    while IFS= read -r path; do
      cp "$path" "$LOGS/display-$(basename "$path")" || true
    done < <(find "$OUTPUT" -maxdepth 1 -name '*.log' -type f)
    if [ -f "$OUTPUT/gdb-stop.json" ]; then
      cp "$OUTPUT/gdb-stop.json" "$LOGS/display-class-snapshot.log" || true
    fi
  fi
  exit "$result"
}
trap collect_display_logs EXIT

python3 - <<'PY' 2>&1 | tee "$LOGS/display-class-capture.log"
import subprocess

candidate = 'build/native-prelink/native-owner-mobile-graphics-candidate.macho'
command = ['python3', 'scripts/probe-darwinboot-xnu.py', '--kernel', candidate,
           '--prelink-report', candidate.replace('.macho', '.json'),
           '--output', 'build/darwinboot-owner-hvf-mobile-graphics-legacy-class',
           '--break-symbol', '__ZN11OSMetaClassC2EPKcPKS_j', '--finish-function',
           '--entry-kernel-bytes-field', '1:0:' + b'IOMobileFramebufferLegacy\0'.hex(),
           '--entry-max-skips', '4096', '--load-mobile-graphics',
           '--armvirt', '--qemu-vmm-present', '--armcpu', '--timeout', '180',
           '--nvram-proxy', '--crypto-hash-method', 'sha2-384', '--amfi-platform-only']
subprocess.run(command, check=True)
PY
mkdir -p build/display-analysis
python3 scripts/audit-mobile-graphics-legacy.py 2>&1 | tee "$LOGS/display-class-audit.log"
