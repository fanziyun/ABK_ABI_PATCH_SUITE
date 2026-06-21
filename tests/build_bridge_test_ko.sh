#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MAINLINE_ROOT="${1:-${ABK_MAINLINE_7012_ROOT:-$MODULE_DIR/../../linux}}"
OUT_DIR="${2:-$MODULE_DIR/out}"
KBUILD_OUT="${3:-$OUT_DIR/build}"
TARGET_ARCH="${ABK_BRIDGE_TEST_ARCH:-arm64}"
DEFCONFIG_TARGET="${ABK_BRIDGE_TEST_DEFCONFIG:-defconfig}"

if [ ! -d "$MAINLINE_ROOT" ]; then
  printf 'mainline root not found: %s\n' "$MAINLINE_ROOT" >&2
  exit 1
fi

mkdir -p "$OUT_DIR" "$KBUILD_OUT"

if [ ! -f "$KBUILD_OUT/.config" ]; then
  make -C "$MAINLINE_ROOT" \
    O="$KBUILD_OUT" \
    ARCH="$TARGET_ARCH" \
    LLVM=1 \
    "$DEFCONFIG_TARGET"
fi

"$MAINLINE_ROOT/scripts/config" --file "$KBUILD_OUT/.config" \
  -e MODULES \
  -e MODVERSIONS \
  -e MODULE_UNLOAD

make -C "$MAINLINE_ROOT" \
  O="$KBUILD_OUT" \
  ARCH="$TARGET_ARCH" \
  LLVM=1 \
  olddefconfig \
  modules_prepare

make -C "$MAINLINE_ROOT" \
  O="$KBUILD_OUT" \
  ARCH="$TARGET_ARCH" \
  LLVM=1 \
  M="$MODULE_DIR/ko" \
  modules

cp -a "$MODULE_DIR/ko/abk_bridge_test.ko" "$OUT_DIR/abk_bridge_test.ko"
printf '%s\n' "$OUT_DIR/abk_bridge_test.ko"
