#!/bin/bash
# AuroraOS script 17 — VirtualBox Guest Additions (7.2.12) for dynamic display
# resize (the desktop follows the VM window) on the VMSVGA controller.
#
# Builds vboxguest/vboxsf/vboxvideo against the AuroraOS kernel, installs the
# GA userland, and wires VBoxService as a systemd service. VBoxService itself
# spawns /usr/bin/VBoxDRMClient, which drives the vmwgfx DRM resize.
#
# Requires: the kernel source tree at /sources/linux-6.13.4 (already built),
# working DNS, and CONFIG_DRM_VMWGFX=y in the running kernel (script 13/kernel).
# Run inside the LFS chroot.
set -e
GA_VER=7.2.12
KVER=6.13.4
KSRC=/sources/linux-$KVER
ISO=/tmp/ga.iso
PAY=/tmp/ga-amd64

# 1) fetch + unpack (skip if already present)
if [ ! -d "$PAY" ]; then
  [ -f "$ISO" ] || python3 - <<PY
import urllib.request
u="https://download.virtualbox.org/virtualbox/$GA_VER/VBoxGuestAdditions_$GA_VER.iso"
req=urllib.request.Request(u,headers={"User-Agent":"AuroraBuild/1.0"})
open("$ISO","wb").write(urllib.request.urlopen(req,timeout=300).read())
PY
  xorriso -osirrox on -indev "$ISO" -extract /VBoxLinuxAdditions.run /tmp/VBoxLinuxAdditions.run 2>/dev/null
  rm -rf /tmp/ga; sh /tmp/VBoxLinuxAdditions.run --noexec --keep --target /tmp/ga >/dev/null 2>&1 || true
  rm -rf "$PAY"; mkdir -p "$PAY"
  tar xf /tmp/ga/VBoxGuestAdditions-amd64.tar.bz2 -C "$PAY"
fi

# 2) build the kernel modules against the AuroraOS kernel
cd "$PAY/src/vboxguest-$GA_VER"
make KERN_DIR="$KSRC" KERN_VER="$KVER" -j"$(nproc)" >/dev/null
echo "modules: $(ls *.ko | tr '\n' ' ')"

# 3) install modules
install -Dm644 vboxguest.ko /lib/modules/$KVER/misc/vboxguest.ko
install -Dm644 vboxsf.ko    /lib/modules/$KVER/misc/vboxsf.ko
install -Dm644 vboxvideo.ko /lib/modules/$KVER/misc/vboxvideo.ko
depmod "$KVER"

# 4) install userland (VBoxDRMClient must be setuid root — it drives DRM resize)
install -Dm755  "$PAY/sbin/VBoxService"   /usr/sbin/VBoxService
install -Dm755  "$PAY/bin/VBoxControl"    /usr/bin/VBoxControl
install -Dm755  "$PAY/bin/VBoxClient"     /usr/bin/VBoxClient
install -Dm4755 "$PAY/bin/VBoxDRMClient"  /usr/bin/VBoxDRMClient
install -Dm755  "$PAY/other/mount.vboxsf" /sbin/mount.vboxsf

# 5) autoload vboxguest at boot
mkdir -p /etc/modules-load.d
printf 'vboxguest\nvboxsf\n' > /etc/modules-load.d/vboxadd.conf

# 6) run VBoxService at boot (it spawns VBoxDRMClient for resize)
cat > /etc/systemd/system/vboxadd.service <<'EOF'
[Unit]
Description=VirtualBox Guest Additions (display resize + host integration)
After=systemd-modules-load.service
[Service]
Type=simple
ExecStartPre=-/usr/bin/modprobe vboxguest
ExecStart=/usr/sbin/VBoxService --foreground
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/vboxadd.service \
       /etc/systemd/system/multi-user.target.wants/vboxadd.service

echo "GUEST ADDITIONS INSTALLED"
ls -la /usr/bin/VBoxDRMClient /usr/sbin/VBoxService /lib/modules/$KVER/misc/vboxguest.ko
