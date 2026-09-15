# DaybreakOS — an LFS-based distro with its own native desktop and on-device AI

DaybreakOS is built with **Linux From Scratch 12.3 (systemd)**. It boots into a
fully custom desktop environment — **Aurora Shell**, written in C with GTK3 and
`gtk-layer-shell` over the `labwc` Wayland compositor. Not a browser kiosk and
not an off-the-shelf desktop: the top bar, dock, app launcher, wallpaper, and
the **Aura** assistant are all Aurora's own code. Aura is an on-device LLM
(llama.cpp + a quantized Qwen2.5-1.5B-Instruct model) that both chats and controls the desktop —
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
  arch (`AURORA_ARCH` auto-detects). For aarch64 — including running DaybreakOS
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
| 9 | `scripts/09-bootloader.sh` | GRUB (UEFI) + DaybreakOS entry | 5 min |
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
- **Aura is a real on-device LLM.** Script 13 builds `llama-server` (llama.cpp).
  The model is **Qwen2.5-1.5B-Instruct** (Q4_K_M, about 1.0 GB, Apache-2.0), bundled by
  script 02 or downloaded after install with "Set up Aura (AI)". `aurorad`
  exposes `/ask`, which runs deterministic fast-paths for common commands (open
  terminal, open app, status, brightness) and defers open-ended chat to the
  model. Power off and restart never run from Aura directly: it asks, and only a
  click on its Power off / Restart button does it. It's a small model on CPU, so
  answers are useful but not cloud-grade; swap the GGUF in `/opt/aura/models`
  for a larger one if you have the RAM.
- `llama-server`'s shared libs are installed to `/usr/lib` (its build tree under
  `/sources` is excluded from the squashfs), and the launcher auto-selects the
  largest bundled model.

## Aura evaluation

73 cases: 40 tool requests, 25 messages that must not trigger a tool, 8 power requests. Measured with llama.cpp `b4589` on the development host; latency is only comparable within this table. Generated by `python tests/aura_eval.py --summary --markdown`.

*Model* columns score the model's own output. *Pipeline* columns run that same output through `aura_llm.ask()`, whose keyword gate (`_ACTION_CUE`) drops a tool call when the request contains no action word. Some realistic requests, such as "how much battery is left", have none, so pipeline accuracy sits below model accuracy by design; the per-tool table shows where. Not covered by these cases: out-of-range brightness values and empty input. The *system facts, no tool* column counts replies that quote battery, network or uptime numbers without calling a tool, a heuristic for invented readings. The *cut off output* column counts outputs that start as JSON but hit the token limit before closing it; one that had begun a tool call counts as a false action, and Aura shows a fallback reply for it that can wrongly say the language model is not installed. Each model and decoding was run three times because the model samples randomly; the table lists every run. The baseline's 0% pipeline false-action rate on power requests came from the model inventing command names such as `poweroff`, not from a safety check: the registered `power` tool still existed then, and Aura now asks for confirmation instead. If schema decoding raises `open_app` accuracy, that is the schema restricting commands to real tool names rather than the model understanding requests better. Latency was measured on a Windows development PC, not on DaybreakOS target hardware. Other work shared that PC's CPU during the runs, so latency is noisy: generation speed for single requests at times fell to about half its median. Accuracy and false-action rates do not depend on speed. Qwen2.5-1.5B's high schema p95 comes from outputs that repeat a tool call until the token limit, not from load.

<!-- aura-eval:start -->
| model | decoding | date | tool acc (model) | tool acc (pipeline) | args acc | false action (model) | false action (pipeline) | valid response JSON | bad reply | cut off output | system facts, no tool | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| llama-3.2-1b-q4km-baseline | free | 2026-09-15 | 57.5% (23/40) | 50.0% (20/40) | 50.0% (8/16) | 60.6% (20/33) | 0.0% (0/33) | 95.0% (38/40) | 0.0% (0/73) | 0.0% (0/73) | - | 1461 | 3159 |
| llama-3.2-1b-q4km-r1 | free | 2026-09-15 | 57.5% (23/40) | 52.5% (21/40) | 50.0% (8/16) | 45.5% (15/33) | 0.0% (0/33) | 92.5% (37/40) | 0.0% (0/73) | 1.4% (1/73) | 9.6% (7/73) | 1480 | 2892 |
| llama-3.2-1b-q4km-r1 | schema | 2026-09-15 | 72.5% (29/40) | 60.0% (24/40) | 56.2% (9/16) | 51.5% (17/33) | 33.3% (11/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 2.7% (2/73) | 1447 | 2338 |
| llama-3.2-1b-q4km-r2 | free | 2026-09-15 | 57.5% (23/40) | 50.0% (20/40) | 50.0% (8/16) | 51.5% (17/33) | 0.0% (0/33) | 95.0% (38/40) | 0.0% (0/73) | 2.7% (2/73) | 11.0% (8/73) | 1524 | 2435 |
| llama-3.2-1b-q4km-r2 | schema | 2026-09-15 | 72.5% (29/40) | 60.0% (24/40) | 62.5% (10/16) | 57.6% (19/33) | 33.3% (11/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 4.1% (3/73) | 1436 | 2580 |
| llama-3.2-1b-q4km-r3 | free | 2026-09-15 | 60.0% (24/40) | 50.0% (20/40) | 50.0% (8/16) | 48.5% (16/33) | 0.0% (0/33) | 92.5% (37/40) | 0.0% (0/73) | 1.4% (1/73) | 9.6% (7/73) | 1711 | 3590 |
| llama-3.2-1b-q4km-r3 | schema | 2026-09-15 | 72.5% (29/40) | 62.5% (25/40) | 68.8% (11/16) | 60.6% (20/33) | 39.4% (13/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 2.7% (2/73) | 1764 | 3047 |
| qwen2.5-1.5b-q4km-r1 | free | 2026-09-15 | 87.5% (35/40) | 72.5% (29/40) | 68.8% (11/16) | 42.4% (14/33) | 3.0% (1/33) | 97.5% (39/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 2564 | 5088 |
| qwen2.5-1.5b-q4km-r1 | schema | 2026-09-15 | 80.0% (32/40) | 67.5% (27/40) | 75.0% (12/16) | 30.3% (10/33) | 3.0% (1/33) | 100.0% (40/40) | 0.0% (0/73) | 6.9% (5/73) | 2.7% (2/73) | 2620 | 14175 |
| qwen2.5-1.5b-q4km-r2 | free | 2026-09-15 | 80.0% (32/40) | 70.0% (28/40) | 68.8% (11/16) | 42.4% (14/33) | 3.0% (1/33) | 97.5% (39/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 2206 | 3841 |
| qwen2.5-1.5b-q4km-r2 | schema | 2026-09-15 | 82.5% (33/40) | 70.0% (28/40) | 81.2% (13/16) | 30.3% (10/33) | 6.1% (2/33) | 100.0% (40/40) | 0.0% (0/73) | 8.2% (6/73) | 2.7% (2/73) | 2417 | 15302 |
| qwen2.5-1.5b-q4km-r3 | free | 2026-09-15 | 77.5% (31/40) | 70.0% (28/40) | 68.8% (11/16) | 39.4% (13/33) | 3.0% (1/33) | 97.5% (39/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 2219 | 4124 |
| qwen2.5-1.5b-q4km-r3 | schema | 2026-09-15 | 80.0% (32/40) | 67.5% (27/40) | 75.0% (12/16) | 30.3% (10/33) | 3.0% (1/33) | 100.0% (40/40) | 0.0% (0/73) | 8.2% (6/73) | 4.1% (3/73) | 2318 | 14024 |
| qwen2.5-3b-q4km-r1 | free | 2026-09-15 | 97.5% (39/40) | 75.0% (30/40) | 87.5% (14/16) | 36.4% (12/33) | 3.0% (1/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 1.4% (1/73) | 4226 | 7019 |
| qwen2.5-3b-q4km-r1 | schema | 2026-09-15 | 97.5% (39/40) | 77.5% (31/40) | 81.2% (13/16) | 33.3% (11/33) | 21.2% (7/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 4574 | 9047 |
| qwen2.5-3b-q4km-r2 | free | 2026-09-15 | 100.0% (40/40) | 77.5% (31/40) | 93.8% (15/16) | 36.4% (12/33) | 3.0% (1/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 1.4% (1/73) | 4418 | 6706 |
| qwen2.5-3b-q4km-r2 | schema | 2026-09-15 | 100.0% (40/40) | 77.5% (31/40) | 81.2% (13/16) | 33.3% (11/33) | 21.2% (7/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 4515 | 9147 |
| qwen2.5-3b-q4km-r3 | free | 2026-09-15 | 97.5% (39/40) | 75.0% (30/40) | 87.5% (14/16) | 39.4% (13/33) | 3.0% (1/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 1.4% (1/73) | 4293 | 7496 |
| qwen2.5-3b-q4km-r3 | schema | 2026-09-15 | 97.5% (39/40) | 77.5% (31/40) | 87.5% (14/16) | 30.3% (10/33) | 21.2% (7/33) | 100.0% (40/40) | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/73) | 4550 | 6914 |

| model | decoding | tool | cases | model correct | pipeline correct |
|---|---|---|---|---|---|
| llama-3.2-1b-q4km-baseline | free | list_apps | 8 | 7 | 7 |
| llama-3.2-1b-q4km-baseline | free | open_app | 8 | 0 | 0 |
| llama-3.2-1b-q4km-baseline | free | open_terminal | 8 | 6 | 6 |
| llama-3.2-1b-q4km-baseline | free | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-baseline | free | system_status | 8 | 2 | 1 |
| llama-3.2-1b-q4km-r1 | free | list_apps | 8 | 7 | 7 |
| llama-3.2-1b-q4km-r1 | free | open_app | 8 | 0 | 0 |
| llama-3.2-1b-q4km-r1 | free | open_terminal | 8 | 6 | 6 |
| llama-3.2-1b-q4km-r1 | free | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r1 | free | system_status | 8 | 2 | 2 |
| llama-3.2-1b-q4km-r1 | schema | list_apps | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r1 | schema | open_app | 8 | 1 | 1 |
| llama-3.2-1b-q4km-r1 | schema | open_terminal | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r1 | schema | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r1 | schema | system_status | 8 | 4 | 3 |
| llama-3.2-1b-q4km-r2 | free | list_apps | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r2 | free | open_app | 8 | 0 | 0 |
| llama-3.2-1b-q4km-r2 | free | open_terminal | 8 | 6 | 6 |
| llama-3.2-1b-q4km-r2 | free | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r2 | free | system_status | 8 | 1 | 1 |
| llama-3.2-1b-q4km-r2 | schema | list_apps | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r2 | schema | open_app | 8 | 2 | 2 |
| llama-3.2-1b-q4km-r2 | schema | open_terminal | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r2 | schema | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r2 | schema | system_status | 8 | 3 | 2 |
| llama-3.2-1b-q4km-r3 | free | list_apps | 8 | 7 | 7 |
| llama-3.2-1b-q4km-r3 | free | open_app | 8 | 0 | 0 |
| llama-3.2-1b-q4km-r3 | free | open_terminal | 8 | 6 | 6 |
| llama-3.2-1b-q4km-r3 | free | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r3 | free | system_status | 8 | 3 | 1 |
| llama-3.2-1b-q4km-r3 | schema | list_apps | 8 | 8 | 7 |
| llama-3.2-1b-q4km-r3 | schema | open_app | 8 | 3 | 3 |
| llama-3.2-1b-q4km-r3 | schema | open_terminal | 8 | 7 | 7 |
| llama-3.2-1b-q4km-r3 | schema | set_brightness | 8 | 8 | 6 |
| llama-3.2-1b-q4km-r3 | schema | system_status | 8 | 3 | 2 |
| qwen2.5-1.5b-q4km-r1 | free | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r1 | free | open_app | 8 | 7 | 6 |
| qwen2.5-1.5b-q4km-r1 | free | open_terminal | 8 | 7 | 7 |
| qwen2.5-1.5b-q4km-r1 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-1.5b-q4km-r1 | free | system_status | 8 | 7 | 4 |
| qwen2.5-1.5b-q4km-r1 | schema | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r1 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r1 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r1 | schema | set_brightness | 8 | 7 | 5 |
| qwen2.5-1.5b-q4km-r1 | schema | system_status | 8 | 3 | 2 |
| qwen2.5-1.5b-q4km-r2 | free | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r2 | free | open_app | 8 | 7 | 6 |
| qwen2.5-1.5b-q4km-r2 | free | open_terminal | 8 | 7 | 7 |
| qwen2.5-1.5b-q4km-r2 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-1.5b-q4km-r2 | free | system_status | 8 | 4 | 3 |
| qwen2.5-1.5b-q4km-r2 | schema | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r2 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r2 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r2 | schema | set_brightness | 8 | 7 | 5 |
| qwen2.5-1.5b-q4km-r2 | schema | system_status | 8 | 4 | 3 |
| qwen2.5-1.5b-q4km-r3 | free | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r3 | free | open_app | 8 | 6 | 5 |
| qwen2.5-1.5b-q4km-r3 | free | open_terminal | 8 | 7 | 7 |
| qwen2.5-1.5b-q4km-r3 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-1.5b-q4km-r3 | free | system_status | 8 | 4 | 4 |
| qwen2.5-1.5b-q4km-r3 | schema | list_apps | 8 | 6 | 6 |
| qwen2.5-1.5b-q4km-r3 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r3 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-1.5b-q4km-r3 | schema | set_brightness | 8 | 7 | 5 |
| qwen2.5-1.5b-q4km-r3 | schema | system_status | 8 | 3 | 2 |
| qwen2.5-3b-q4km-r1 | free | list_apps | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r1 | free | open_app | 8 | 7 | 6 |
| qwen2.5-3b-q4km-r1 | free | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r1 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r1 | free | system_status | 8 | 8 | 4 |
| qwen2.5-3b-q4km-r1 | schema | list_apps | 8 | 7 | 7 |
| qwen2.5-3b-q4km-r1 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r1 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r1 | schema | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r1 | schema | system_status | 8 | 8 | 4 |
| qwen2.5-3b-q4km-r2 | free | list_apps | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | free | open_app | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | free | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r2 | free | system_status | 8 | 8 | 4 |
| qwen2.5-3b-q4km-r2 | schema | list_apps | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r2 | schema | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r2 | schema | system_status | 8 | 8 | 4 |
| qwen2.5-3b-q4km-r3 | free | list_apps | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r3 | free | open_app | 8 | 7 | 6 |
| qwen2.5-3b-q4km-r3 | free | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r3 | free | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r3 | free | system_status | 8 | 8 | 4 |
| qwen2.5-3b-q4km-r3 | schema | list_apps | 8 | 7 | 7 |
| qwen2.5-3b-q4km-r3 | schema | open_app | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r3 | schema | open_terminal | 8 | 8 | 7 |
| qwen2.5-3b-q4km-r3 | schema | set_brightness | 8 | 8 | 6 |
| qwen2.5-3b-q4km-r3 | schema | system_status | 8 | 8 | 4 |
<!-- aura-eval:end -->

## After first boot

Login is automatic on tty1 as the unprivileged `aurora` user, which starts
`labwc`; its autostart launches `aura-llm-launch` (the Aura LLM server),
`aurorad` (system bridge on 127.0.0.1:7212), and `aurora-shell` (the desktop).
Click **◆ Aura** in the top bar to chat with the assistant or give it commands;
the first reply after boot waits a few seconds for the model to load. **◇ Store**
opens the Daybreak Store to install apps in one click, and **▦ Apps** opens the
searchable launcher. Open a terminal from the dock or with **Super+Return**
(`foot`); close windows with the titlebar **×**, **Alt+F4**, or **Super+Q**. TTY2 (Ctrl-Alt-F2) gives you a
normal shell — user `aneek`, password set during script 7.

## Installing & running applications

DaybreakOS boots into **labwc** (a small Wayland compositor); the Aurora shell is the
base layer and native apps float on top. Open a terminal with **Super+Return**
(`foot`). Ways to get software onto the system:

- **Daybreak Store** (easiest — one click). Click **◇ Store** in the top bar for a
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
