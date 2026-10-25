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
# 内核按 UUID 选 Data 卷。macOS 不能给 APFS 卷指定 UUID，所以 Data 种子先造、
# 读出它实际的 UUID，再作为 XNU_OWNER_DATA_VOLUME_UUID 编进内核；defconfig 里
# 那个值只是默认。
if [ -n "${DATA_SEED_UUID:-}" ]; then
  # 构建器会用 .config 覆盖环境变量，必须修改最终生效的配置。
  python3 - "$ROOT/out/sheng/.config" "$DATA_SEED_UUID" <<'PY_DATA_CONFIG'
from pathlib import Path
import re
import sys
import uuid
path = Path(sys.argv[1])
value = str(uuid.UUID(sys.argv[2])).upper()
text, count = re.subn(r'^CONFIG_XNU_OWNER_DATA_VOLUME_UUID=.*$',
                     'CONFIG_XNU_OWNER_DATA_VOLUME_UUID="' + value + '"',
                     path.read_text(), flags=re.M)
if count != 1:
    raise SystemExit('Expected exactly one Data UUID in the effective config')
path.write_text(text)
print('effective kernel Data volume UUID: ' + value)
PY_DATA_CONFIG
fi
./unixnu build kernel
test -s out/sheng/kernel/kernel.macho
test -s out/sheng/kernel/kernel.json
if [ -n "${DATA_SEED_UUID:-}" ]; then
  # 日志中出现新值不代表它已编入产物，直接核对最终预链接内核。
  python3 - "$ROOT/out/sheng/kernel/kernel.macho" "$DATA_SEED_UUID" <<'PY_DATA_KERNEL'
from pathlib import Path
import sys
import uuid
value = str(uuid.UUID(sys.argv[2])).upper()
if value.encode() not in Path(sys.argv[1]).read_bytes():
    raise SystemExit('Built kernel does not contain the actual Data seed UUID')
print('Verified actual Data seed UUID in the built kernel: ' + value)
PY_DATA_KERNEL
fi
