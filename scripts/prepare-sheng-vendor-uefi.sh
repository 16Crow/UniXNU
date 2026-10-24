#!/usr/bin/env bash
# 从官方 sheng 系统包提取固件数据，保留原始内容及下载校验。
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TREE=$ROOT/out/sheng/tree
cd "$TREE"
mkdir -p build/tools/uefiextract
ARCHIVE=build/tools/uefiextract/A75.zip
curl -fL --retry 3 \
  https://github.com/LongSoft/UEFITool/releases/download/A75/UEFIExtract_NE_A75_universal_mac.zip \
  -o "$ARCHIVE"
echo "8cbdd6d42193d6fb8a0c37dc860b4695c618f923b8ecfff9c0042fbdd80aaa80  $ARCHIVE" | shasum -a 256 -c -
unzip -o "$ARCHIVE" -d build/tools/uefiextract
mv build/tools/uefiextract/UEFIExtract build/tools/uefiextract/uefiextract
chmod +x build/tools/uefiextract/uefiextract
# 固件导入器依赖完整下载和解包清单，不用别的机型数据代替。
python3 scripts/download-sheng-firmware.py --connections 16
python3 scripts/extract-sheng-firmware.py --delete-archive
# 组装树的 UEFI 和 firmware 目录都是链接，先解析真实位置再计算相对路径。
python3 - <<'PY'
from pathlib import Path
script = Path('scripts/import-sheng-uefi.py')
text = script.read_text()
replacements = {
    'os.path.relpath(output, link.parent)': 'os.path.relpath(output.resolve(), link.parent.resolve())',
    'link.resolve() != output:': 'link.resolve() != output.resolve():',
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit('Unexpected firmware importer link handling: ' + old)
    text = text.replace(old, new)
script.write_text(text)
PY
python3 scripts/import-sheng-uefi.py
test -s uefi-sheng/Binaries/sheng/RawFiles/SecParti.cfg
