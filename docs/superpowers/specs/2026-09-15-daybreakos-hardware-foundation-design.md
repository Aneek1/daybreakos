# DaybreakOS hardware foundation: design

**Date:** 2026-09-15
**Status:** approved in brainstorming, awaiting owner review of this document
**Depends on:** `config/build.conf` (kernel pin), `config/kernel.fragment`, `config/kernel-x86_64.fragment`, `scripts/08-kernel.sh`, `scripts/09-bootloader.sh`, `scripts/11-make-iso.sh`, `scripts/build-full-iso.sh`, `scripts/13-aurora-desktop.sh`, `scripts/21-xwayland.sh`, `shell/aurorad.py` (installer), `shell/aurora-desktop/aurora-shell.c`
**Followed by (separate specs):** gaming (Mesa upgrade, Vulkan, NVK or the NVIDIA driver, Steam), CAD, installing `.deb` applications

## 1. Why

The owner wants DaybreakOS to run games, CAD tools and applications downloaded as `.deb` files. A read-only survey of the build scripts (2026-09-15) found that none of that can start yet, because the base system has not been shown to boot and work on a real PC:

- The shipped ISO (`build-full-iso.sh:61`) has no EFI partition that firmware can see when the image is written to a USB stick, and the live initramfs only probes `/dev/sr0`, `/dev/vdb` and `/dev/sdb` (`11-make-iso.sh:29-34`), so an NVMe laptop never finds the stick.
- GPU drivers are built into the kernel, but nothing delivers their firmware at boot: the live initramfs is BusyBox only, installed systems have no initramfs, and the firmware fetch used in July was never committed.
- The compositor draws on the CPU (`renderers=` empty, `WLR_RENDERER=pixman`).
- There is no session D-Bus bus, no logind session, no sound server, and the volume slider calls `amixer`, which is never built.
- Intel Wi-Fi cannot work (`CONFIG_IWLMVM` missing), and there is no Wi-Fi firmware or userspace, no Bluetooth, no USB audio, no webcam, touchpad or exFAT/NTFS support, and CIFS is off although the Network Drives feature mounts CIFS.

Full findings: the survey and the laptop research are saved outside the repo (`aura-eval/daybreak-compat-survey-2026-09-15.json`, `aura-eval/daybreak-laptop-hw-research-2026-09-15.json`); the facts this design relies on are repeated here with their sources.

## 2. Target machine

The first supported machine is the owner's laptop, **Lenovo 83LY (Legion 5 15IRX10)**, inventoried from Windows on 2026-09-15:

| Part | Device | Linux driver |
|---|---|---|
| CPU | Intel Core i7-13650HX (Raptor Lake-HX) | intel_pstate, pinctrl-alderlake, LPSS |
| iGPU | Intel UHD Graphics `8086:A78B` | i915 |
| dGPU | NVIDIA GeForce RTX 5060 Laptop GPU `10DE:2D19` (Blackwell) | nouveau (module, power management only in this milestone) |
| Wi-Fi | Intel Wi-Fi 6 AX203 `8086:7A70` | iwlwifi + iwlmvm |
| Bluetooth | Intel USB `8087:0026` | btusb + btintel |
| Audio | Intel Smart Sound DSP `8086:7A50`, Realtek ALC257 codec | snd_hda_intel or SOF, chosen at boot by snd_intel_dspcfg |
| Ethernet | Realtek RTL8111/8168 `10EC:8168` | r8169 |
| Storage | UMIS NVMe 1 TB | nvme |
| Camera | USB `5986:2175` | uvcvideo |
| Touchpad | I2C HID `ELAN06FA` | i2c-hid-acpi + hid-multitouch |

In Windows both the internal panel and the external monitor are connected to the RTX 5060: the laptop runs in discrete (MUX) mode.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| 1 | Hardware foundation first; gaming, CAD and `.deb` installs are later specs | All three depend on booting with working GPU, audio, network and a login session |
| 2 | First target: the Lenovo 83LY above | The owner's test machine |
| 3 | The laptop is switched to **Hybrid** GPU mode; the desktop runs on the Intel GPU; the RTX 5060 is only powered down in this milestone | Intel graphics are already covered by the Mesa build; NVIDIA rendering belongs to the gaming spec |
| 4 | Standard Linux service stack: NetworkManager, BlueZ, PipeWire with WirePlumber, Linux-PAM with systemd-logind, polkit, UPower, udisks2 | Browsers, Steam, Zoom and Flatpak apps expect these interfaces |
| 5 | Secure Boot is turned off for this milestone and documented as a requirement | Signed boot (MOK or shim) is its own project |
| 6 | Proven in QEMU now; the laptop test waits until the owner has a USB stick | No USB stick available; the laptop is a work machine, so its internal disk is not repartitioned |
| 7 | A curated firmware subset is bundled: a committed script fetches pinned upstream releases and copies only the files the enabled drivers need, with licence files | Keeps the ISO small and the repo free of binaries |
| 8 | Kernel moves from 6.13.4 to the current 7.2 stable release (7.2.5 or newer) | 6.13 cannot bind the RTX 5060, and a GPU with no driver is never runtime-suspended, so it would stay powered |
| 9 | One real initramfs, used by both the live USB and installed systems | Firmware for built-in drivers must be present before the root filesystem is mounted |
| 10 | Mesa stays at 24.3.4; the compositor switches to the GLES2 renderer | GPU compositing on Intel works with the current Mesa; Vulkan, NVK and a Rust toolchain belong to the gaming spec |
| 11 | Hardware support is described by per-machine manifests that drive the build and the tests | Kernel fragment merges drop options silently; the manifest makes every requirement checkable |

## 4. Scope

In scope:

- Kernel 7.2.x with a manifest-generated configuration and a check that nothing requested was dropped.
- Curated firmware for every device in section 2.
- An initramfs generator, a USB-bootable ISO layout, and an installer that installs the initramfs.
- GPU compositing on the Intel GPU, and runtime power management for the RTX 5060.
- The login session and service stack in decision 4, and the desktop shell controls that use them.
- `daybreak-hwcheck`, automated QEMU boot tests, and a checklist for the real laptop.

Out of scope:

- Mesa upgrade, Vulkan loader and drivers, NVK, Rust, and the proprietary NVIDIA driver (gaming spec).
- Secure Boot signing.
- Printing (CUPS), multi-monitor layout settings, fingerprint readers, Thunderbolt/USB4 device authorisation.
- Machines other than the 83LY. The manifest format is designed for more, but none are added here.
- Changing the Aura power path: the confirm buttons keep calling aurorad's `/system/power`.

## 5. Components

### 5.1 Hardware manifests

`config/hardware/common.conf` holds requirements every machine has. `config/hardware/lenovo-83ly.conf` holds this laptop's. Both are INI files read with Python's `configparser`, so the C build and shell scripts depend only on the generated outputs.

Each section describes one device or feature:

```ini
[wifi]
match = pci:8086:7A70
kernel = CFG80211=m MAC80211=m IWLWIFI=m IWLMVM=m RFKILL=y
firmware = intel/iwlwifi/iwlwifi-so-a0-hr-b0-89.ucode regulatory.db regulatory.db.p7s
early = no
packages = networkmanager wpa_supplicant wireless-regdb
check = wifi
```

- `kernel`: Kconfig symbols and values.
- `firmware`: paths inside the pinned firmware trees. Links are resolved and kept.
- `early`: `yes` puts the firmware (and the module, if the driver is a module) into the initramfs.
- `packages`: userspace components the build must provide. These are names checked against the build scripts, not a package manager.
- `check`: the name of a check `daybreak-hwcheck` runs on the booted machine.

The manifest for the 83LY carries the symbols and firmware from the laptop research. It covers:

- **Platform:** `PINCTRL_ALDERLAKE`, `X86_INTEL_LPSS`, `MFD_INTEL_LPSS_PCI`, `I2C_DESIGNWARE_CORE`/`PLATFORM`, `INTEL_VSEC`, `INTEL_PMT_TELEMETRY`, `INTEL_PMC_CORE`, `ACPI_WMI=y`, `IDEAPAD_LAPTOP`, `NVIDIA_WMI_EC_BACKLIGHT`, and thermal drivers.
- **Intel GPU:** `DRM_I915=y`, `DRM_XE=n`. Early firmware: `i915/adls_dmc_ver2_01.bin`, `i915/tgl_guc_70.bin` and `i915/tgl_huc.bin`. i915 enables GuC submission by default on Raptor Lake-S, so GuC must be present when it probes.
- **NVIDIA GPU:** `DRM_NOUVEAU=m`. Firmware: `nvidia/gb202/gsp/fmc-570.144.bin`, `nvidia/gb202/gsp/bootloader-570.144.bin`, and `nvidia/ga102/gsp/gsp-570.144.bin` (about 63.6 MB) with the `gb202/gsp` link and the `gb203`, `gb205`, `gb206` and `gb207` directory links. Not early.
- **Bluetooth:** `BT`, `BT_HCIBTUSB`, `BT_RFCOMM`, `BT_BNEP` and `BT_HIDP`. Firmware: `intel/ibt-0040-0041.{sfi,ddc}` and `intel/ibt-1040-0041.{sfi,ddc}`, both shipped because the CNVi step is unknown.
- **Audio:** `SND_HDA_INTEL`, `SND_HDA_CODEC_REALTEK`, `SND_HDA_CODEC_HDMI`, and the SOF chain (`SND_SOC_SOF_PCI`, `SND_SOC_SOF_INTEL_TOPLEVEL`, `SND_SOC_SOF_ALDERLAKE`, `SND_SOC_SOF_HDA_LINK`, `SND_SOC_SOF_HDA_AUDIO_CODEC`, `SND_SOC_INTEL_SKL_HDA_DSP_GENERIC_MACH`). Firmware: the SOF Raptor Lake-S firmware and HDA generic topology from a pinned sof-bin release, plus `alsa-ucm-conf`. Whether the laptop has a digital microphone array, which decides SOF or legacy HDA, is unknown, so both paths ship.
- **Ethernet:** `R8169`. Firmware: `rtl_nic/rtl8168h-2.fw`, `rtl8168g-3.fw` and `rtl8168fp-3.fw` (the chip revision is unknown).
- **Other devices:** `BLK_DEV_NVME`, `VMD`, UVC (`MEDIA_SUPPORT`, `MEDIA_USB_SUPPORT`, `VIDEO_DEV`, `USB_VIDEO_CLASS`), `I2C_HID_ACPI` and `HID_MULTITOUCH`.

`common.conf` covers:

- **Boot:** `BLK_DEV_INITRD`, `USB_STORAGE`, `USB_UAS`, `ISO9660_FS`, `SQUASHFS`, `OVERLAY_FS`.
- **Filesystems:** `EXFAT_FS`, `NTFS3_FS`, `FUSE_FS`, `CIFS`, `NLS_UTF8`.
- **Sleep:** `SUSPEND`, `PM_SLEEP`.
- **Input:** `INPUT_UINPUT`.
- **Firmware loading:** `FW_LOADER_COMPRESS` stays off (firmware is shipped uncompressed).

### 5.2 Generators and checks (`scripts/hw/`)

- `gen-kernel-fragment.py <machine>...` merges `common.conf` with the named machine manifests and writes `build/kernel-hw.fragment`. If two sections ask for different values of the same symbol, it stops and names both.
- `check-kernel-config.py <.config> <machine>...` runs after the kernel's `merge_config.sh` and `olddefconfig`. For every requested symbol whose final value differs, it prints the symbol, the requested and final values, and the symbol's `depends on` line from the kernel tree, then exits non-zero.
- `fetch-firmware.sh <machine>...` downloads pinned releases: linux-firmware tag `20260910`, sof-bin, and wireless-regdb. It verifies each archive against a SHA-256 value committed in `config/hardware/firmware-sources.conf`, copies the listed files with their links into the image's `/lib/firmware`, and copies each file's licence (named in `WHENCE`) to `/usr/share/licenses/firmware/`. A missing file or checksum mismatch stops the build.
- `mkinitramfs <kernel-version> <output>` builds the initramfs (section 6).

### 5.3 Kernel

`config/build.conf` moves to the latest 7.2 stable release when the plan is written (7.2.5 or newer). `scripts/08-kernel.sh` applies `kernel.fragment`, `kernel-x86_64.fragment` and the generated `kernel-hw.fragment`, then runs `check-kernel-config.py`. `DRM_NOUVEAU` changes from `y` to `m`. `CONFIG_EXTRA_FIRMWARE` is not used.

### 5.4 Compositor

wlroots and labwc are rebuilt with `renderers=gles2`, and `pixman` stays available. The session script `shell/aurora-session-gpu` picks the GPU:

1. Read `/sys/class/drm/card*/device/vendor`. Put Intel (`0x8086`) cards first in `WLR_DRM_DEVICES`, then any others.
2. If a card exposes a render node and EGL reports a hardware renderer, set `WLR_RENDERER=gles2`.
3. Otherwise set `WLR_RENDERER=pixman`, and write the reason to the journal. This covers VirtualBox and llvmpipe-only machines.

`GDK_GL=disable` is removed from the session where GLES2 is used.

### 5.5 ISO layout

`build-full-iso.sh` appends the EFI system partition image as a GPT/MBR partition (`xorriso -append_partition 2 0xef boot/efi.img` with the matching boot catalog options), so the same image boots from optical media and from a USB stick written byte for byte. The ISO volume label stays `DAYBREAKOS`.

## 6. Boot flow

### 6.1 Live USB

1. UEFI firmware finds the appended EFI partition and starts GRUB.
2. GRUB loads the 7.2 kernel and the initramfs.
3. The initramfs `init` mounts `/proc`, `/sys` and `/dev`, then loads the early modules the manifests list: NVMe, xHCI, USB storage, UAS, SCSI disk, isofs, squashfs, overlay.
4. It waits up to 30 seconds for a block device whose filesystem label is `DAYBREAKOS`, on any kind of drive.
5. It mounts the ISO, then the squashfs. The overlay's upper layer is the existing `AURORA_DATA` persistence if present, otherwise tmpfs. It then `switch_root`s to systemd.
6. If no labelled device appears in time, it prints what it was looking for, lists every block device with its label and size, saves the kernel log tail to `/run/initramfs/boot-failure.log`, and starts an emergency shell. It does not panic.

### 6.2 Installed system

- The installer in `aurorad.py` copies the kernel and a matching initramfs to the ESP/boot directory, and writes a GRUB entry with an `initrd` line and `root=PARTUUID=...`.
- The initramfs loads the NVMe driver, mounts the ext4 root and switches to it.
- Installing a new kernel runs `mkinitramfs` for that version.

### 6.3 Firmware placement

- **In the initramfs:** firmware for early devices. On the 83LY that is the three i915 files. i915 stays built in; the kernel unpacks the initramfs before built-in drivers probe, so their firmware requests succeed.
- **On the root filesystem:** everything else, loaded when the module loads after root is mounted. That covers Wi-Fi, Bluetooth, Ethernet, the regulatory database, SOF, and the RTX 5060 GSP firmware.

### 6.4 GPUs at runtime

systemd-udevd loads nouveau for the RTX 5060, and GSP-RM starts. With nothing using the GPU, nouveau's runtime power management suspends it. The check reads `/sys/bus/pci/devices/<dGPU>/power/runtime_status` and expects `suspended`. The compositor uses the Intel card (section 5.4).

## 7. Services and the login session

- **Session:** `greetd` starts the desktop for the `aurora` user through Linux-PAM (`pam_systemd`). The session gets a logind seat, `XDG_RUNTIME_DIR`, a D-Bus user bus and `systemd --user`. This replaces the getty autologin and the `dbus-run-session` wrapper in `scripts/13-aurora-desktop.sh`. Device access comes from logind's session ACLs rather than hand-assigned groups.
- **Audio:** PipeWire, WirePlumber and pipewire-pulse run as user services, and PipeWire's BlueZ plugin handles Bluetooth audio. alsa-utils is installed for diagnostics.
- **Network:** NetworkManager with wpa_supplicant replaces systemd-networkd. systemd-resolved stays.
- **System services:** BlueZ (`bluetoothd`), UPower, udisks2 and polkit.
- **Policy:** polkit's standard rules let the active local session manage Wi-Fi, Bluetooth, removable-drive mounts and suspend without a password.
- **Power keys:** logind handles the lid (`HandleLidSwitch=suspend`, s2idle). The power key opens the existing power confirmation instead of powering off.

Desktop shell additions, over D-Bus with GDBus (already linked through GLib):

- a Wi-Fi network list with connect and password entry (NetworkManager)
- Bluetooth on/off and paired devices (BlueZ)
- a volume slider and output device picker (WirePlumber), replacing the `amixer` calls
- a battery indicator (UPower)
- suspend (logind)
- a notice when a removable drive is attached, with open and eject (udisks2)

If a service or device is missing, as with Bluetooth in VirtualBox, the shell hides that control and shows a one-line note in the control centre.

aurorad keeps its root-only jobs: install to disk, the Store and `/system/power`.

## 8. Error handling

| Situation | Behaviour |
|---|---|
| Kernel option dropped by the merge | Build fails, naming the symbol, requested and final values, and its `depends on` line |
| Two manifest sections disagree on a symbol | Fragment generation fails, naming both sections |
| Firmware archive checksum mismatch or listed file absent | Firmware fetch fails, naming the file and release |
| Live medium not found | Emergency shell with the searched label, the block device list and `/run/initramfs/boot-failure.log` |
| Driver loaded but firmware missing, device absent, or check failing after boot | `daybreak-hwcheck` records it in `/var/log/daybreak/hwcheck.json` and the shell shows a notice naming the device and the missing piece |
| No hardware GPU acceleration | Compositor uses pixman; the reason is written to the journal |
| Service unavailable | Its shell control is hidden with a note |

## 9. Testing

### 9.1 Unit tests (Windows, seconds, no downloads)

`tests/test_hw_manifest.py`:

- manifests parse and every section has the required keys
- conflicting symbol values are detected
- the generated fragment matches the manifests
- every symbol exists in a committed symbol list extracted from the pinned 7.2 kernel (`config/hardware/kconfig-symbols-7.2.txt`)
- every firmware path exists in committed file listings of the pinned firmware releases (`config/hardware/firmware-tree-20260910.txt` and the sof-bin listing), with links resolved

Tests for `check-kernel-config.py` use small fake `.config` files, including one with a dropped symbol.

### 9.2 Build checks (WSL)

- `check-kernel-config.py` against the real final `.config`.
- A listing of the generated initramfs (`cpio -t`) confirms the early modules and firmware are inside.
- `scripts/check-shell-build.sh` still reports no new warnings.

### 9.3 QEMU boot tests (WSL, UEFI firmware, headless)

`scripts/99-smoke-qemu.sh` gains three scenarios. Pass or fail is read from markers printed on the serial console.

1. **Live USB:** the ISO attached as `usb-storage`, next to an empty emulated NVMe disk. Expected: the initramfs finds `DAYBREAKOS`, systemd reaches the greetd session, `loginctl` shows an active seat, and `wpctl status` lists an audio sink (QEMU `intel-hda`).
2. **Install:** an unattended install to the NVMe disk, then a reboot from NVMe with the ISO detached. Expected: the same session markers.
3. **Missing medium:** boot the kernel and initramfs with no labelled device. Expected: the emergency shell message within 40 seconds.

QEMU has no Intel GPU, so scenarios 1 and 2 also expect the pixman fallback message. The existing VirtualBox VM gets a manual regression pass.

### 9.4 Laptop checklist (when a USB stick is available)

1. In the BIOS or Lenovo Vantage, set the GPU mode to Hybrid and turn Secure Boot off.
2. Write the ISO to a USB stick with Rufus in DD mode, and boot from it.
3. Run `daybreak-hwcheck --report`, which guides through about 20 minutes of checks:
   - Intel GPU rendering with `gles2`, and the RTX 5060 `suspended`
   - Wi-Fi scan and connection, and a Bluetooth scan
   - speaker, headphone and HDMI audio, and microphone detection
   - touchpad, including two-finger scroll, and camera (`/dev/video0` delivers frames)
   - lid-close suspend and resume
   - exFAT USB drive mount, and a battery reading
4. Share the report file so failures can be turned into fixes.

### 9.5 Done

- The milestone is done when sections 9.1-9.3 pass on the build.
- The laptop report in section 9.4 is the hardware sign-off, recorded in the README when it happens.
- Until then the README states that real-hardware support is untested.

## 10. Risks

- **Nouveau on Blackwell is new:** GB20x support first shipped in Linux 6.16, and display fixes landed in 7.2.5 and 7.3 (September 2026). Runtime suspend on this laptop is unverified until the laptop test.
- **Unknown hardware details:** the digital-microphone question (SOF vs HDA), the CNVi step (which Bluetooth firmware name) and the Realtek Ethernet revision are unknown. The design ships every candidate and `daybreak-hwcheck` reports which one loaded.
- **Hybrid mode wiring:** in Hybrid mode, the laptop's HDMI or USB-C ports may still be wired to the RTX 5060. External displays on those ports may not work in this milestone.
- **Rebuild and re-validation cost:** the 7.2 kernel and the service stack are large LFS builds. VirtualBox graphics (VMSVGA) and the installer must be validated again.
- **ISO size:** the firmware subset adds about 70 MB, mostly the NVIDIA GSP image. The service stack adds more. The size is reported at the end of each build.
- **Sessions and aurorad:** moving to PAM and logind sessions changes how aurorad's session instance is started. The Aura tests must still pass.

## 11. Order of work

1. Manifests, generators and unit tests.
2. Kernel 7.2 build with the kernel config check.
3. Firmware fetch.
4. initramfs, the live boot path and the USB ISO layout, with QEMU scenario 1 (boot only) and scenario 3.
5. Installer changes, with QEMU scenario 2.
6. The session, PAM and logind, and the services.
7. GPU compositing and dGPU power management.
8. Desktop shell controls.
9. `daybreak-hwcheck`, the full QEMU markers, and the README hardware section.
