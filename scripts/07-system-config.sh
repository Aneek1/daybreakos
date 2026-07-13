#!/bin/bash
# AuroraOS 07 — system configuration + branding. Run INSIDE the chroot.
set -e
. /aurora/config/build.conf 2>/dev/null || { DISTRO_NAME=AuroraOS; DISTRO_VERSION=1.0; DISTRO_CODENAME=daybreak; DISTRO_USER=aneek; }
# build.conf's STAMPS is $LFS-prefixed (host side); inside the chroot the stamp
# dir is an absolute /var path. Pin it here so it survives the source above.
STAMPS=/var/lib/aurora-build
mkdir -p "$STAMPS"

ROOTDEV=$(grep ROOT /.aurora-disk 2>/dev/null | cut -d= -f2)
ESPDEV=$(grep ESP /.aurora-disk 2>/dev/null | cut -d= -f2)

# fstab
cat > /etc/fstab <<EOF
# AuroraOS fstab
${ROOTDEV:-/dev/sda2}  /          ext4  defaults            1 1
${ESPDEV:-/dev/sda1}   /boot/efi  vfat  umask=0077          0 1
EOF

# hostname + network (systemd-networkd, DHCP on everything)
echo aurora > /etc/hostname
mkdir -p /etc/systemd/network
cat > /etc/systemd/network/10-dhcp.network <<"EOF"
[Match]
Name=en* eth*

[Network]
DHCP=yes
EOF
systemctl enable systemd-networkd systemd-resolved 2>/dev/null || true
ln -sfv /run/systemd/resolve/resolv.conf /etc/resolv.conf

# os-release + branding
cat > /etc/os-release <<EOF
NAME="$DISTRO_NAME"
VERSION="$DISTRO_VERSION ($DISTRO_CODENAME)"
ID=auroraos
PRETTY_NAME="$DISTRO_NAME $DISTRO_VERSION"
VERSION_CODENAME=$DISTRO_CODENAME
HOME_URL="https://aneek1.github.io"
EOF
echo "$DISTRO_VERSION" > /etc/lfs-release
cat > /etc/lsb-release <<EOF
DISTRIB_ID=$DISTRO_NAME
DISTRIB_RELEASE=$DISTRO_VERSION
DISTRIB_CODENAME=$DISTRO_CODENAME
DISTRIB_DESCRIPTION="$DISTRO_NAME $DISTRO_VERSION"
EOF
install -m644 /aurora/branding/issue /etc/issue
install -m644 /aurora/branding/motd  /etc/motd

# console + locale
cat > /etc/vconsole.conf <<"EOF"
KEYMAP=us
EOF
cat > /etc/locale.conf <<"EOF"
LANG=en_SG.UTF-8
EOF
cat > /etc/profile <<"EOF"
export LANG=en_SG.UTF-8
export PS1='\u@\h:\w\$ '
EOF

# users
# set_pw <user>: non-interactive when AURORA_DEFAULT_PASS is exported (live/ISO
# builds), otherwise prompt (disk installs).
set_pw(){
  if [ -n "${AURORA_DEFAULT_PASS:-}" ]; then
    echo "$1:${AURORA_DEFAULT_PASS}" | chpasswd
    echo "== password for $1 set from AURORA_DEFAULT_PASS =="
  else
    echo "== set password for $1 =="
    passwd "$1"
  fi
}
set_pw root
if ! id "$DISTRO_USER" &>/dev/null; then
  useradd -m -G wheel,audio,video,input -s /bin/bash "$DISTRO_USER"
  set_pw "$DISTRO_USER"
fi
# kiosk user (no password login, no shell)
id aurora &>/dev/null || useradd -r -m -d /var/lib/aurora -G video,input,seat -s /usr/bin/false aurora

touch $STAMPS/ch9-config
echo "== 07 complete — run /aurora/scripts/08-kernel.sh =="
