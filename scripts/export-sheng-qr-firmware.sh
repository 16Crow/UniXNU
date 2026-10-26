#!/usr/bin/env bash
# 禁止系统产物上传 GitHub；保留旧工作流入口，避免影响正常构建。
set -euo pipefail
printf '%s\n' '::notice::GitHub image exports are disabled; no files were uploaded.'
