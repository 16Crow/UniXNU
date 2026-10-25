#!/usr/bin/env bash
# 加密取回本次启动与系统盘镜像，明文产物不进入公开附件。
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
: "${UNIXNU_EXPORT_PASSWORD:?Missing private export password}"
: "${GH_TOKEN:?Missing GitHub release token}"
STAGE=$RUNNER_TEMP/sheng-private-export
mkdir -p "$STAGE"
FILES=(boot/boot.img boot/boot.json payload/payload.json)
# 系统卷内容不变时只取回启动镜像，复用本地已完整校验的系统盘。
if [[ " ${STEPS:-} " == *" userdata "* ]]; then
  FILES+=(userdata/userdata-root.img userdata/userdata-root.json)
fi
for FILE in "${FILES[@]}"; do
  test -s "out/sheng/$FILE"
done
# 流式加密和分段，避免在 runner 上额外存放整份未压缩归档。
tar -C out/sheng -cf - "${FILES[@]}" \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt -pass env:UNIXNU_EXPORT_PASSWORD \
  | split -b 1800m -d -a 2 - "$STAGE/sheng-images.enc.part."
(cd "$STAGE" && shasum -a 256 sheng-images.enc.part.* > SHA256SUMS)
TAG=sheng-private-$GITHUB_RUN_ID
gh release create "$TAG" --repo "$GITHUB_REPOSITORY" --draft --target "$GITHUB_SHA" \
  --title "sheng private build $GITHUB_RUN_ID" --notes 'Encrypted images for the owner; no plaintext firmware or system image attachments.'
gh release upload "$TAG" "$STAGE"/* --repo "$GITHUB_REPOSITORY"
echo "Encrypted images stored in private draft release $TAG"
