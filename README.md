# AuroraOS — an LFS-based distro with its own native desktop and on-device AI

AuroraOS is built with **Linux From Scratch 12.3 (systemd)**. It boots into a
fully custom desktop environment — **Aurora Shell**, written in C with GTK3 and
`gtk-layer-shell` over the `labwc` Wayland compositor. Not a browser kiosk and
not an off-the-shelf desktop: the top bar, dock, app launcher, wallpaper, and
the **Aura** assistant are all Aurora's own code. Aura is an on-device LLM
(llama.cpp + a bundled Qwen2.5 model) that both chats and controls the desktop —
"open a terminal", "system status", "set brightness to 40" — running entirely
offline, no cloud.

```
┌──────────────────────────────────────────────────────┐
│  aurora-shell  (native C/GTK3 desktop: bar, dock,     │
│                 launcher, wallpaper, Aura panel)      │
│      │  raw socket → 127.0.0.1:7212 (aurorad)         │
│      │                     │  /ask → 127.0.0.1:8080   │
│  aurorad.py (system bridge)    llama-server (Aura LLM)│
│      │  /sys, systemctl, subprocess, app launch       │
│  labwc (Wayland compositor) · LFS 12.3 base · kernel  │
└──────────────────────────────────────────────────────┘
```

## Requirements

- A build host (or VM) with a distro that passes `00-check-host.sh` (Debian 12 / Ubuntu 24.04 work)
- **Architectures:** x86_64 and aarch64. The build host's arch is the target
  arch (`AURORA_ARCH` auto-detects). For aarch64 — including running AuroraOS
  on Apple Silicon in a VM — see `docs/build-host-utm.md`.
- A spare disk or virtual disk (≥ 30 GB) — **it will be wiped**
- 4+ cores, 8+ GB RAM, and patience: **6–12 hours of compilation** (~200 SBU total)
- Run everything as root inside the VM, from this repo's root

Quick QEMU build host:

```bash
qemu-img create -f qcow2 aurora-build.qcow2 40G
qemu-system-x86_64 -enable-kvm -m 8G -smp 4 \
  -drive file=debian12.qcow2 -drive file=aurora-build.qcow2 \
  -bios /usr/share/ovmf/OVMF.fd
```

## Build order

| # | Script | What it does | Time |
|---|--------|--------------|------|
| 0 | `scripts/00-check-host.sh` | Verify host tools per LFS ch. 2 | 1 min |
| 1 | `scripts/01-prepare-disk.sh` | Partition + mount `$LFS` (DESTRUCTIVE) | 1 min |
| 2 | `scripts/02-download-sources.sh` | Fetch LFS source list + extras, verify md5 | 10 min |
| 3 | `scripts/03-toolchain-pass1.sh` | Cross toolchain: binutils, gcc, glibc… (LFS ch. 5) | ~1 h |
| 4 | `scripts/04-temp-tools.sh` | Temporary tools (LFS ch. 6) | ~1 h |
| 5 | `scripts/05-enter-chroot.sh` | Mount virtual FS + chroot | — |
| 6 | `scripts/06-base-system.sh` | Full base system in chroot (LFS ch. 7–8) | 3–6 h |
| 7 | `scripts/07-system-config.sh` | Users, network, fstab, os-release, branding | 5 min |
| 8 | `scripts/08-kernel.sh` | Kernel with `config/kernel.fragment` | ~30 min |
| 9 | `scripts/09-bootloader.sh` | GRUB (UEFI) + AuroraOS entry | 5 min |
| 10 | `scripts/10-aurora-shell.sh` | Wayland stack, Firefox, shell, aurorad, services | 1–3 h |
| 12 | `scripts/12-apps.sh` | External-app stack: labwc compositor + foot terminal + AppImage/Nix helpers | 30 min |
| 13 | `scripts/13-aurora-desktop.sh` | **Native Aurora desktop**: gtk-layer-shell, `aurora-shell`, Aura LLM (llama.cpp + model), labwc session + autologin | 1–2 h |
| 11 | `scripts/11-make-iso.sh` | Optional: squashfs live ISO (run last) | 20 min |

Scripts 3–4 run on the host; 6–10 run **inside the chroot** (script 5 prints the
exact command). Every script sources `config/build.conf` and is idempotent-ish:
finished packages are skipped via stamp files in `$LFS/var/lib/aurora-build/`.

## Honesty notes (read before building)

- These scripts **track the LFS 12.3 book**. LFS is precise; if a package fails,
  the book (https://www.linuxfromscratch.org/lfs/view/12.3-systemd/) is the
  canonical reference — fix per book, re-run, the stamp system resumes.
- `06-base-system.sh` implements the ~80 base packages as a recipe table:
  the fiddly ones (glibc, gcc, binutils, perl, python…) have explicit recipes;
  standard autotools packages go through a generic recipe.
- The desktop is **native**, not a web page. `shell/aurora-desktop/aurora-shell.c`
  is compiled in script 13 against GTK3 + `gtk-layer-shell`; `style.css` carries
  the "daybreak" theme. The GTK3 stack is built from `config/extras.list` — the
  pragmatic deviation from "pure" LFS, and the longest part of scripts 10/13.
- **Aura is a real on-device LLM.** Script 13 builds `llama-server` (llama.cpp)
  and bundles a quantized **Qwen2.5-3B-Instruct** GGUF. `aurorad` exposes `/ask`,
  which runs deterministic fast-paths for common commands (open terminal, open
  app, status, brightness, power) and defers open-ended chat to the model. It's
  a small model on CPU, so answers are useful but not cloud-grade; swap the GGUF
  in `/opt/aura/models` for a larger one if you have the RAM.
- `llama-server`'s shared libs are installed to `/usr/lib` (its build tree under
  `/sources` is excluded from the squashfs), and the launcher auto-selects the
  largest bundled model.

## After first boot

Login is automatic on tty1 as the unprivileged `aurora` user, which starts
`labwc`; its autostart launches `aura-llm-launch` (the Aura LLM server),
`aurorad` (system bridge on 127.0.0.1:7212), and `aurora-shell` (the desktop).
Click **◆ Aura** in the top bar to chat with the assistant or give it commands;
the first reply after boot waits a few seconds for the model to load. **◇ Store**
opens the Aurora Store to install apps in one click, and **▦ Apps** opens the
searchable launcher. Open a terminal from the dock or with **Super+Return**
(`foot`); close windows with the titlebar **×**, **Alt+F4**, or **Super+Q**. TTY2 (Ctrl-Alt-F2) gives you a
normal shell — user `aneek`, password set during script 7.

## Installing & running applications

AuroraOS boots into **labwc** (a small Wayland compositor); the Aurora shell is the
base layer and native apps float on top. Open a terminal with **Super+Return**
(`foot`). Ways to get software onto the system:

- **Aurora Store** (easiest — one click). Click **◇ Store** in the top bar for a
  curated catalog of GTK apps (calculator, text editor, notes, system monitor…).
  Hit **Get** and aurorad downloads the app's AppImage, unpacks it under
  `~/Applications` (extract-and-run — no FUSE needed), and drops a launcher into
  the app grid; the button flips to **Open**. The catalog is a plain
  pipe-delimited file at `/usr/share/aurora/store/catalog` (`id|name|category|
  icon|description|github-repo-or-url`) — add a line to add an app. Entries can
  pin a direct URL or name a GitHub repo whose latest x86_64 `.AppImage` release
  is resolved at install time, so the catalog survives version bumps.
- **Nix** (recommended for CLI/dev tools). Run `aurora-get-nix` once (needs
  network), then `nix profile install nixpkgs#<pkg>`. Installed apps appear in the
  shell's **Installed** list automatically (aurorad scans `~/.nix-profile`).
- **AppImage** — drop a `*.AppImage` into `~/Apps`, `chmod +x` it; it shows up in
  the launcher and runs directly (fuse3 is built in).
- **Build from source** (BLFS-style) for anything you want in the base.
- **Flatpak** is planned (phase 2) — its dependency chain isn't built yet.

Design + rationale: `docs/superpowers/specs/2026-07-10-external-apps-design.md`.

## Roadmap: Apple Silicon bare metal

The aarch64 port is workstream A of the M4 bare-metal plan — see
`docs/superpowers/specs/2026-07-10-m4-baremetal-design.md`. Bare-metal M4
(m1n1/t8132 bringup) is workstream B and has its own milestone ladder.
