#!/bin/bash
# 清理过期的上传文件和导出文件
# 默认：uploads/exports 保留 7 天，uploads/tmp 保留 1 天
#
# 用法：
#   DRY_RUN=1 bash scripts/cleanup_old_files.sh   # 只打印，不删除
#   bash scripts/cleanup_old_files.sh             # 实际删除

set -euo pipefail

DAYS="${DAYS:-7}"
TMP_DAYS="${TMP_DAYS:-1}"
UPLOAD_DIR="${UPLOAD_DIR:-/data/luotu/uploads}"
EXPORT_DIR="${EXPORT_DIR:-/data/luotu/exports}"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "[$(date '+%F %T')] $*"; }

clean_dir() {
  local dir="$1" days="$2"
  [ -d "$dir" ] || return 0
  if [ "$DRY_RUN" = "1" ]; then
    find "$dir" -maxdepth 1 -type f -mtime +"$days" -printf '  would delete %p (%s bytes)\n'
  else
    find "$dir" -maxdepth 1 -type f -mtime +"$days" -delete
  fi
}

log "cleanup start (dry_run=$DRY_RUN, days=$DAYS, tmp_days=$TMP_DAYS)"
clean_dir "$UPLOAD_DIR" "$DAYS"
clean_dir "$EXPORT_DIR" "$DAYS"
clean_dir "$UPLOAD_DIR/tmp" "$TMP_DAYS"
log "cleanup done"
