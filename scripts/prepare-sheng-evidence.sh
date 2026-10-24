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

# 先确认真实候选能到达采集点，再生成存储元类的精确读取请求。
# 失败时保留原始日志，不能把超时或 panic 当作已获得有效审计证据。
python3 scripts/probe-darwinboot-xnu.py \
  --kernel "$CANDIDATES/native-apfs-load-positive.macho" \
  --output build/darwinboot-storage-preflight \
  --break-symbol _bsd_init --timeout 120 \
  2>&1 | tee "$ROOT/out/sheng/logs/qemu-storage-preflight.log"
