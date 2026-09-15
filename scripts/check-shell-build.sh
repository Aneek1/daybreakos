#!/bin/bash
# Compile-check aurora-shell with the same steps as scripts/build-full-iso.sh.
# Needs: build-essential pkg-config libgtk-3-dev libgtk-layer-shell-dev libwayland-dev
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../shell/aurora-desktop" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
XML="$SRC/protocols/wlr-foreign-toplevel-management-unstable-v1.xml"
wayland-scanner client-header "$XML" "$OUT/wlr-foreign-toplevel-management-unstable-v1-client-protocol.h"
wayland-scanner private-code "$XML" "$OUT/wlr-foreign-toplevel-management-unstable-v1-protocol.c"
if ! cc -Wall -Wno-unused-parameter "$SRC/aurora-shell.c" \
        "$OUT/wlr-foreign-toplevel-management-unstable-v1-protocol.c" -I"$OUT" -O2 -o "$OUT/aurora-shell" \
        $(pkg-config --cflags --libs gtk+-3.0 gtk-layer-shell-0 wayland-client) -lm 2> "$OUT/cc.txt"; then
    cat "$OUT/cc.txt"; exit 1
fi
echo "aurora-shell built: $(stat -c %s "$OUT/aurora-shell") bytes, $(grep -c 'warning:' "$OUT/cc.txt" || true) warnings"
grep 'warning:' "$OUT/cc.txt" | sed 's#^.*/##' | sort | uniq || true
