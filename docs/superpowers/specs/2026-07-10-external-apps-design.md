# AuroraOS — running external applications

**Date:** 2026-07-10
**Status:** Approved (design)
**Depends on:** the shipped LFS base + Wayland stack (scripts 00–11)

## Problem

AuroraOS boots `cage -d -- firefox --kiosk index.html`. **cage is a single-window
kiosk compositor** — it shows exactly one fullscreen client and cannot display a
second window. So today the "apps" in the shell are HTML inside one Firefox
instance; no native program can appear on screen. To be a dual-boot daily driver,
AuroraOS needs to (a) *display* native windows and (b) have a way to *install* them
— LFS ships neither a multi-window compositor session nor a package manager.

## Two independent axes

### Axis 1 — Display: replace cage with **labwc**

`labwc` is a small wlroots-based **stacking** compositor. wlroots, libinput,
seatd, and the whole Wayland stack are already built (`extras.list`), so labwc is
a modest addition. Model:

```
labwc (compositor)
  ├─ Firefox (Aurora shell)  — launched maximized, the always-present base
  └─ native apps             — open as floating windows ON TOP of the shell
```

The web shell stays the face of the OS; native apps stack above it and close back
to it. No kiosk lock-in. `foot` (terminal) is the escape hatch and is built here
(it was whitelisted in `aurorad` but never actually built — a pre-existing gap).

### Axis 2 — Install: Nix + AppImage now, Flatpak later

LFS has no package manager. Ranked by fit and build cost:

| Path | Role | Build cost in this script |
|---|---|---|
| **Nix** | primary source for CLI/dev software (~100k prebuilt pkgs), installs under `/nix`, never touches the LFS tree | none at build time — a first-boot helper runs the official single-user installer (needs network once) |
| **AppImage** | zero-install single-file GUI apps | build `fuse3` (small); apps then run directly |
| **foot** | terminal — gateway to everything else | built here (+ `fcft`, `tllist`) |
| **Flatpak** | sandboxed GUI apps | **deferred to phase 2** — its dep chain (ostree, bubblewrap, appstream, polkit, xdg-dbus-proxy…) is large; documented, not built now |

## The launcher: `aurorad` becomes real

Today `aurorad`'s `/launch` is a 2-item hardcoded whitelist. It grows into a real
launcher backed by the freedesktop `.desktop` standard:

- **`GET /apps`** — enumerate installed apps by scanning `.desktop` files in
  `/usr/share/applications`, `~/.local/share/applications`, the Nix profile
  (`~/.nix-profile/share/applications`), and Flatpak exports (later). Returns
  `[{id, name, icon, exec}]`.
- **`POST /launch {id}`** — look the id up in the scanned set and spawn its `Exec`
  (with Wayland env). **Security:** it launches only ids that came from a real
  discovered `.desktop` file — the shell can't pass an arbitrary command string.
  Still localhost-only, still the `aurora` user.

The shell's Start menu gains an **"Installed"** section that fetches `/apps` and
launches via `/launch`. AppImages dropped in `~/Apps` are surfaced too (a synthetic
.desktop-less entry).

## Architecture after this change

```
labwc
 ├─ aurora-session: firefox (shell)  ← base window
 ├─ foot                              ← terminal
 └─ <any installed app>              ← launched via shell → aurorad /launch
aurorad  → /apps (discover) · /launch (spawn) · existing status/files/power/ask
apps come from:  Nix (/nix) · AppImage (~/Apps) · built-from-source · Flatpak(later)
```

## Known tradeoff (accepted for v1)

Two window systems coexist: the shell manages its **web** apps (div windows:
Files, Notepad…), labwc manages **native** windows. A user sees both. The clean
unification — make the shell a `layer-shell` background/panel so it's purely the
launcher+taskbar and *all* real windows are native — is a larger project
(effectively a full desktop environment) and is **out of scope for v1**. v1's goal
is simply: you can install and run real apps on AuroraOS.

## Scripts / files touched

- **New `scripts/12-apps.sh`** — build `fcft`+`tllist`+`foot`, `labwc`, `fuse3`;
  write labwc config; rewrite the session to launch labwc; install the
  `aurora-get-nix` first-boot helper; create `~/Apps`.
- **`config/extras.list`** — add foot/fcft/tllist/labwc/fuse3 source URLs.
- **`shell/aurora-session`** — `cage …` → `labwc -s aurora-startup` (startup runs
  firefox + optionally foot).
- **`shell/aurorad.py`** — add `/apps`, upgrade `/launch` to id-based spawn from
  discovered `.desktop` files.
- **`shell/index.html` + `aurora-bridge.js`** — Start-menu "Installed" section
  populated from `/apps`; clicking launches via `/launch`.
- **README** — document installing apps (nix/appimage/foot) and the labwc session.

## Verification

- Build correctness (labwc/foot/fuse3 compile, scripts parse) — checkable in the
  aarch64 container; **display behavior (labwc showing windows) needs a real GPU/
  display**, so the acceptance test is on the M4/VM: boot → shell appears under
  labwc → `foot` opens as a window → install one Nix pkg → it launches from the
  shell's Installed list.
- `aurorad /apps` returns real entries from `.desktop` scan; `/launch {id}` spawns
  only discovered ids (attempt to launch an unknown id → 403).
