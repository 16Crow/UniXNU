#!/usr/bin/env bash
# 构建完整图形组件及必需的真实回放数据，不运行额外测试套件。
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TREE=$ROOT/out/sheng/tree
cd "$TREE"
brew install glslang shaderc spirv-tools vulkan-headers pkgconf
# 工具必须位于组装树，源码和生成产物才能与内核使用同一份输入。
cp "$ROOT/scripts/prepare-sheng-mesa.py" scripts/prepare-sheng-mesa.py
cp "$ROOT/scripts/check-turnip-darwin-host.py" scripts/check-turnip-darwin-host.py
python3 scripts/prepare-sheng-mesa.py
python3 scripts/build-turnip-darwin.py --target host
python3 scripts/build-turnip-darwin.py --target ios
python3 scripts/check-turnip-darwin-host.py --build-only

python3 - <<'PY'
import json
import subprocess
from pathlib import Path

pins = json.loads(Path('scripts/data/gpu-metal-vulkan-inputs.json').read_text())['translator']
source = Path('.cache/gpu-reference/metal2vulkan')
if not (source / '.git').exists():
    source.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'remote', 'add', 'origin', pins['repository']], check=True)
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1', 'origin', pins['commit']], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
PY
rustup toolchain install 1.98.0 --profile minimal
rustup target add --toolchain 1.98.0 aarch64-apple-ios
python3 scripts/build-adreno-metal-plugin.py
