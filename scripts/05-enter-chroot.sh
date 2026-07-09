#!/bin/bash
# AuroraOS 05 — prepare and enter chroot (LFS 12.3 ch. 7.2–7.4). Run as root.
set -e
. "$(dirname "$0")/../config/build.conf"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

chown --from lfs -R root:root "$LFS"/{usr,lib64,var,etc,tools} 2>/dev/null || true

mkdir -pv "$LFS"/{dev,proc,sys,run}
mountpoint -q "$LFS/dev"     || mount -v --bind /dev "$LFS/dev"
mountpoint -q "$LFS/dev/pts" || mount -vt devpts devpts -o gid=5,mode=0620 "$LFS/dev/pts"
mountpoint -q "$LFS/proc"    || mount -vt proc proc "$LFS/proc"
mountpoint -q "$LFS/sys"     || mount -vt sysfs sysfs "$LFS/sys"
mountpoint -q "$LFS/run"     || mount -vt tmpfs tmpfs "$LFS/run"
if [ -h "$LFS/dev/shm" ]; then
  install -v -d -m 1777 "$LFS$(realpath /dev/shm)"
else
  mountpoint -q "$LFS/dev/shm" || mount -vt tmpfs -o nosuid,nodev tmpfs "$LFS/dev/shm"
fi

# copy the repo into the chroot so scripts 6–10 are available inside
mkdir -p "$LFS/aurora"
cp -r "$REPO"/{scripts,config,shell,branding,systemd} "$LFS/aurora/"

echo "== entering chroot. Inside, run in order: =="
echo "   /aurora/scripts/06-base-system.sh"
echo "   /aurora/scripts/07-system-config.sh"
echo "   /aurora/scripts/08-kernel.sh"
echo "   /aurora/scripts/09-bootloader.sh"
echo "   /aurora/scripts/10-aurora-shell.sh"
chroot "$LFS" /usr/bin/env -i \
  HOME=/root TERM="$TERM" PS1='(aurora chroot) \u:\w\$ ' \
  PATH=/usr/bin:/usr/sbin MAKEFLAGS="$MAKEFLAGS" /bin/bash --login
