#!/bin/bash
# DaybreakOS 01 — partition and mount the target disk. DESTRUCTIVE.
set -e
. "$(dirname "$0")/../config/build.conf"

echo "!! This will WIPE $LFS_DISK completely. Ctrl-C now to abort."
read -rp "Type the disk name ($LFS_DISK) to confirm: " C
[ "$C" = "$LFS_DISK" ] || { echo "aborted"; exit 1; }

wipefs -a "$LFS_DISK"
parted -s "$LFS_DISK" mklabel gpt \
  mkpart ESP fat32 1MiB 513MiB set 1 esp on \
  mkpart aurora ext4 513MiB 100%

ESP="${LFS_DISK}1"; ROOT="${LFS_DISK}2"
# NVMe naming (nvme0n1p1)
[ -b "${LFS_DISK}p1" ] && { ESP="${LFS_DISK}p1"; ROOT="${LFS_DISK}p2"; }

mkfs.vfat -F32 -n EFI "$ESP"
mkfs.ext4 -L aurora "$ROOT"

mkdir -p "$LFS"
mount "$ROOT" "$LFS"
mkdir -p "$LFS/boot/efi"
mount "$ESP" "$LFS/boot/efi"

mkdir -p "$STAMPS"
echo "ESP=$ESP"  >  "$LFS/.aurora-disk"
echo "ROOT=$ROOT" >> "$LFS/.aurora-disk"
echo "== $ROOT mounted at $LFS — proceed to 02-download-sources.sh =="
echo "   (re-mount with this script's last two mount commands after a host reboot)"
