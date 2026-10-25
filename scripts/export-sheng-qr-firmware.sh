#!/usr/bin/env bash
# 只取回二维码诊断固件；不导出或重建内核、系统盘。
set -euo pipefail
: "${UNIXNU_EXPORT_PASSWORD:?Missing private export password}"
: "${GH_TOKEN:?Missing GitHub release token}"
STAGE=$RUNNER_TEMP/sheng-qr-export
mkdir -p "$STAGE"
FD=uefi-sheng/Build/shengPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
test -s "$FD"
cp "$FD" "$STAGE/SILICIUM_UEFI.fd"
(cd "$STAGE" && shasum -a 256 SILICIUM_UEFI.fd > firmware.sha256)
tar -C "$STAGE" -cf - SILICIUM_UEFI.fd firmware.sha256 \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt -pass env:UNIXNU_EXPORT_PASSWORD \
  > "$STAGE/sheng-qr-firmware.enc"
(cd "$STAGE" && shasum -a 256 sheng-qr-firmware.enc > SHA256SUMS)
TAG=sheng-qr-$GITHUB_RUN_ID
gh release create "$TAG" --repo "$GITHUB_REPOSITORY" --draft --target "$GITHUB_SHA" \
  --title "sheng QR diagnostic $GITHUB_RUN_ID" --notes 'Encrypted diagnostic firmware only.'
gh release upload "$TAG" "$STAGE/sheng-qr-firmware.enc" "$STAGE/SHA256SUMS" --repo "$GITHUB_REPOSITORY"
