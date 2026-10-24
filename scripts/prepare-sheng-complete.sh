#!/usr/bin/env bash
# 补齐板级公开输入后，恢复官方完整配置构建内核。
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TREE=$ROOT/out/sheng/tree
cd "$TREE"

python3 scripts/fetch-sheng-dts.py 2>&1 | tee "$ROOT/out/sheng/logs/sheng-dts-inputs.log"
python3 scripts/fetch-adreno-inputs.py 2>&1 | tee "$ROOT/out/sheng/logs/adreno-inputs.log"

# 旧版板级审计通过文件位置找构建根；原样放入两层目录以兼容组装树。
mkdir -p build/sheng-tools docs
cp "$UNIXNU_DEVICE/package/audit-adreno-platform.py" build/sheng-tools/audit-adreno-platform.py
if [ ! -e docs/adreno-inputs.json ]; then
  ln -s ../scripts/data/adreno-inputs.json docs/adreno-inputs.json
fi
python3 - <<'PY'
from pathlib import Path
for name in ('prepare-sheng-gmu.py', 'prepare-sheng-gmu-votes.py'):
    script = Path('scripts') / name
    text = script.read_text()
    old = "ROOT/'kits/sheng/audit-adreno-platform.py'"
    if text.count(old) != 1:
        raise SystemExit('Unexpected board audit invocation: ' + name)
    script.write_text(text.replace(old, "ROOT/'build/sheng-tools/audit-adreno-platform.py'"))
PY
python3 scripts/prepare-sheng-gmu.py 2>&1 | tee "$ROOT/out/sheng/logs/sheng-gmu-inputs.log"
python3 scripts/prepare-sheng-gmu-votes.py 2>&1 | tee "$ROOT/out/sheng/logs/sheng-gmu-votes.log"
python3 scripts/extract-files.py --device "$UNIXNU_DEVICE" \
  2>&1 | tee "$ROOT/out/sheng/logs/sheng-touch-firmware.log"

# BootProgress 编译使用 UEFI 的真实字体和帧缓冲声明。
if [ ! -d "$ROOT/uefi-sheng/.git" ]; then
  git clone --depth 1 https://github.com/UniXNU/uefi-sheng.git "$ROOT/uefi-sheng"
fi
if [ ! -e "$TREE/uefi-sheng" ]; then
  ln -s "$ROOT/uefi-sheng" "$TREE/uefi-sheng"
fi

cd "$ROOT"
./unixnu defconfig "$DEFCONFIG"
./unixnu build kernel
test -s out/sheng/kernel/kernel.macho
test -s out/sheng/kernel/kernel.json
