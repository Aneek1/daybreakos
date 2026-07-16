#!/bin/bash
# DaybreakOS script 16 — pre-install default apps into the system image so they
# appear in the app drawer out of the box (no Store trip needed). Each is a
# self-contained "anylinux" AppImage, extracted to /opt/aurora-apps/<id> with a
# .desktop written into /usr/share/applications (which the shell's launcher
# scans). Run inside the LFS chroot with working DNS.
set -e

# id | friendly name | category | github repo
APPS=(
  "files|Files|System|domesya/Nemo-AppImage"
  "gnome-calendar|Calendar|Office|fiftydinar/gnome-calendar-appimage"
)

APPDIR=/opt/aurora-apps
mkdir -p "$APPDIR"

resolve() { # repo -> url  (latest x86_64 AppImage)
  python3 - "$1" <<'PY'
import sys,urllib.request,json
gh=sys.argv[1]
api="https://api.github.com/repos/%s/releases/latest"%gh
req=urllib.request.Request(api,headers={"User-Agent":"AuroraBuild/1.0"})
assets=json.loads(urllib.request.urlopen(req,timeout=60).read()).get("assets",[])
u=None
for a in assets:
    n=a.get("name","")
    if "x86_64" in n and n.endswith(".AppImage"): u=a["browser_download_url"];break
if not u:
    for a in assets:
        if a.get("name","").endswith(".AppImage"): u=a["browser_download_url"];break
print(u or "")
PY
}

for entry in "${APPS[@]}"; do
  IFS='|' read -r id name cat repo <<< "$entry"
  echo "==== pre-installing $id ($repo) ===="
  url=$(resolve "$repo")
  [ -n "$url" ] || { echo "  no AppImage for $repo — skipping"; continue; }
  tmp="/tmp/$id.AppImage"; work="/tmp/pi-$id"
  python3 - "$url" "$tmp" <<'PY'
import sys,urllib.request
req=urllib.request.Request(sys.argv[1],headers={"User-Agent":"AuroraBuild/1.0"})
open(sys.argv[2],"wb").write(urllib.request.urlopen(req,timeout=300).read())
PY
  chmod 0755 "$tmp"
  rm -rf "$work"; mkdir -p "$work"
  ( cd "$work" && "$tmp" --appimage-extract >/dev/null 2>&1 )
  src=$(readlink -f "$work/squashfs-root")
  [ -d "$src" ] || { echo "  extract failed for $id"; continue; }
  dest="$APPDIR/$id"
  rm -rf "$dest"; mv "$src" "$dest"
  [ -x "$dest/AppRun" ] || { echo "  no AppRun for $id"; continue; }
  miss=$(ldd "$dest/AppRun" 2>/dev/null | grep -ic "not found" || true)
  echo "  AppRun installed; missing libs: $miss"
  icon="$dest/.DirIcon"; [ -f "$icon" ] || icon="application-x-executable"
  cat > "/usr/share/applications/aurora-$id.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$name
Comment=$name
Exec=$dest/AppRun
Icon=$icon
Categories=$cat;
Terminal=false
DESK
  rm -f "$tmp"; rm -rf "$work"
  echo "  done: $name -> $dest/AppRun"
done
echo "PREINSTALL DONE"
ls -la /usr/share/applications/aurora-*.desktop
