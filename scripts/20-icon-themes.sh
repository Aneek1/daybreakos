#!/bin/bash
# DaybreakOS 20 — real themed icons. Run INSIDE the chroot.
# librsvg + the gdk-pixbuf SVG loader were already in the image; what was
# missing is the icon THEME data, so lookups like "application-x-executable"
# or "folder" drew placeholder glyphs. hicolor is the freedesktop base theme
# (fallback + index.theme); Adwaita is GTK3's default theme name and supplies
# the actual artwork (PNG sizes + symbolic SVGs + cursors).
# Tarballs: hicolor-icon-theme-0.18.tar.xz, adwaita-icon-theme-47.0.tar.xz
set -e
cd /sources/extras

tar xf hicolor-icon-theme-0.18.tar.xz
cd hicolor-icon-theme-0.18
mkdir -p b && cd b && meson setup --prefix=/usr .. && ninja install
cd /sources/extras && rm -rf hicolor-icon-theme-0.18

tar xf adwaita-icon-theme-47.0.tar.xz
cd adwaita-icon-theme-47.0
mkdir -p b && cd b && meson setup --prefix=/usr .. && ninja install
cd /sources/extras && rm -rf adwaita-icon-theme-47.0

gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
gtk-update-icon-cache -f /usr/share/icons/Adwaita

echo "== 20 complete — themed icons available. Re-squash + rebuild ISO. =="
