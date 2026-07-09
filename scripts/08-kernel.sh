#!/bin/bash
# AuroraOS 08 — Linux kernel. Run INSIDE the chroot.
set -e
STAMPS=/var/lib/aurora-build
cd /sources
TB=$(ls linux-*.tar.xz | head -1)
SRC=${TB%.tar.xz}

if [ ! -f $STAMPS/kernel ]; then
  rm -rf $SRC; tar xf $TB; cd $SRC
  make mrproper
  make defconfig
  # merge AuroraOS fragment (graphics, EFI, virtio, squashfs/overlay for live ISO)
  scripts/kconfig/merge_config.sh -m .config /aurora/config/kernel.fragment
  make olddefconfig
  make
  make modules_install
  cp -iv arch/x86/boot/bzImage /boot/vmlinuz-aurora
  cp -iv System.map /boot/System.map-aurora
  cp -iv .config /boot/config-aurora
  cd /sources
  touch $STAMPS/kernel
fi
echo "== 08 complete — run /aurora/scripts/09-bootloader.sh =="
