#!/bin/bash
# AuroraOS script 14 — X11 CLIENT libraries + ALSA + libgpg-error.
#
# AuroraOS runs a pure-Wayland compositor (labwc) and was built without any
# X11 client libraries. But virtually every prebuilt GTK3 app (AppImages in the
# Aurora Store: Xournal++, browsers, GNOME apps, file managers) is linked
# against libX11/libxcb even when it renders through the Wayland backend, so it
# fails to start with "libX11.so.6: cannot open shared object file".
#
# This installs the X11 *client* libraries (no X server) plus ALSA and
# libgpg-error so those apps load and then use the Wayland GDK backend.
#
# Run inside the LFS chroot. Idempotent-ish: re-running rebuilds each package.
set -e

SRC=/sources/x11libs
mkdir -p "$SRC"
export PKG_CONFIG_PATH=/usr/lib/pkgconfig:/usr/share/pkgconfig
export ACLOCAL_PATH=/usr/share/aclocal

XORG_LIB=https://www.x.org/releases/individual/lib
XORG_PROTO=https://www.x.org/releases/individual/proto
XORG_UTIL=https://www.x.org/releases/individual/util
XCB=https://xcb.freedesktop.org/dist
ALSA=https://www.alsa-project.org/files/pub/lib
GPGERR=https://www.gnupg.org/ftp/gcrypt/libgpg-error

# name|url  (built strictly in this order — deps first)
PKGS=(
  "util-macros-1.20.1.tar.xz|$XORG_UTIL/util-macros-1.20.1.tar.xz"
  "xorgproto-2024.1.tar.xz|$XORG_PROTO/xorgproto-2024.1.tar.xz"
  "xtrans-1.5.2.tar.xz|$XORG_LIB/xtrans-1.5.2.tar.xz"
  "libXau-1.0.11.tar.xz|$XORG_LIB/libXau-1.0.11.tar.xz"
  "libXdmcp-1.1.5.tar.xz|$XORG_LIB/libXdmcp-1.1.5.tar.xz"
  "xcb-proto-1.17.0.tar.xz|$XCB/xcb-proto-1.17.0.tar.xz"
  "libxcb-1.17.0.tar.xz|$XCB/libxcb-1.17.0.tar.xz"
  "libX11-1.8.10.tar.xz|$XORG_LIB/libX11-1.8.10.tar.xz"
  "libXext-1.3.6.tar.xz|$XORG_LIB/libXext-1.3.6.tar.xz"
  "libXrender-0.9.11.tar.xz|$XORG_LIB/libXrender-0.9.11.tar.xz"
  "libXfixes-6.0.1.tar.xz|$XORG_LIB/libXfixes-6.0.1.tar.xz"
  "libXi-1.8.2.tar.xz|$XORG_LIB/libXi-1.8.2.tar.xz"
  "libXrandr-1.5.4.tar.xz|$XORG_LIB/libXrandr-1.5.4.tar.xz"
  "libXcursor-1.2.3.tar.xz|$XORG_LIB/libXcursor-1.2.3.tar.xz"
  "libXcomposite-0.4.6.tar.xz|$XORG_LIB/libXcomposite-0.4.6.tar.xz"
  "libXdamage-1.1.6.tar.xz|$XORG_LIB/libXdamage-1.1.6.tar.xz"
  "libXinerama-1.1.5.tar.xz|$XORG_LIB/libXinerama-1.1.5.tar.xz"
  "libXtst-1.2.5.tar.xz|$XORG_LIB/libXtst-1.2.5.tar.xz"
  "libgpg-error-1.50.tar.bz2|$GPGERR/libgpg-error-1.50.tar.bz2"
  "alsa-lib-1.2.12.tar.bz2|$ALSA/alsa-lib-1.2.12.tar.bz2"
)

dl() { # url dest
  python3 - "$1" "$2" <<'PY'
import sys,urllib.request
url,dest=sys.argv[1],sys.argv[2]
req=urllib.request.Request(url,headers={"User-Agent":"AuroraBuild/1.0"})
open(dest,"wb").write(urllib.request.urlopen(req,timeout=180).read())
PY
}

for entry in "${PKGS[@]}"; do
  tb="${entry%%|*}"; url="${entry##*|}"
  dir="${tb%.tar.*}"
  echo "==== $dir ===="
  cd "$SRC"
  [ -f "$tb" ] || dl "$url" "$SRC/$tb"
  rm -rf "$dir"; tar xf "$tb"
  cd "$dir"
  case "$dir" in
    xcb-proto-*)
      ./configure --prefix=/usr >/dev/null
      make install >/dev/null ;;
    util-macros-*|xorgproto-*|xtrans-*)
      ./configure --prefix=/usr --datadir=/usr/share >/dev/null
      make install >/dev/null ;;
    alsa-lib-*)
      ./configure --prefix=/usr --disable-python >/dev/null
      make -j"$(nproc)" >/dev/null 2>&1
      make install >/dev/null ;;
    libgpg-error-*)
      ./configure --prefix=/usr >/dev/null
      make -j"$(nproc)" >/dev/null 2>&1
      make install >/dev/null ;;
    *)
      ./configure --prefix=/usr --disable-static >/dev/null
      make -j"$(nproc)" >/dev/null 2>&1
      make install >/dev/null ;;
  esac
  echo "installed $dir"
done

ldconfig
echo "ALL X11 CLIENT LIBS DONE"
ls /usr/lib/libX11.so.6 /usr/lib/libxcb.so.1 /usr/lib/libasound.so.2 /usr/lib/libgpg-error.so.0
