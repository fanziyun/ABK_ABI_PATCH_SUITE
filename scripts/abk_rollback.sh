#!/usr/bin/env bash
# Restore a kernel tree that a failed suite run left half-patched.
#
# The Python children rewrite one file at a time with no transaction, so a hard
# failure part-way through leaves earlier files already modified. write_text()
# snapshots the original bytes to <file>.abk-orig before its first rewrite;
# this script puts them back.
#
# Usage:
#   bash scripts/abk_rollback.sh <kernel-common-dir> [--list|--apply]
#
# Default is --list (dry run). Nothing is restored until --apply is passed.

set -euo pipefail

BACKUP_SUFFIX=".abk-orig"

usage() {
  cat >&2 <<'EOF'
usage: abk_rollback.sh <kernel-common-dir> [--list|--apply]

  --list   show which files would be restored (default)
  --apply  restore them and remove the backups
EOF
  exit 2
}

[ $# -ge 1 ] || usage

target_dir="$1"
mode="${2:---list}"

[ -d "$target_dir" ] || {
  printf '[ABK rollback][error] not a directory: %s\n' "$target_dir" >&2
  exit 1
}

case "$mode" in
  --list|--apply) ;;
  *) usage ;;
esac

mapfile -t backups < <(find "$target_dir" -type f -name "*${BACKUP_SUFFIX}" | sort)

if [ "${#backups[@]}" -eq 0 ]; then
  printf '[ABK rollback] no %s backups under %s: nothing to restore\n' \
    "$BACKUP_SUFFIX" "$target_dir"
  exit 0
fi

printf '[ABK rollback] found %d backup(s) under %s\n' "${#backups[@]}" "$target_dir"

restored=0
for backup in "${backups[@]}"; do
  original="${backup%${BACKUP_SUFFIX}}"

  if [ "$mode" = "--list" ]; then
    printf '  would restore: %s\n' "$original"
    continue
  fi

  cp -- "$backup" "$original"
  rm -f -- "$backup"
  printf '  restored: %s\n' "$original"
  restored=$((restored + 1))
done

if [ "$mode" = "--list" ]; then
  printf '[ABK rollback] dry run only; re-run with --apply to restore\n'
else
  printf '[ABK rollback] restored %d file(s)\n' "$restored"
fi
