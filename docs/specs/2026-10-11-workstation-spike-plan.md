# Arslan's workstation (the VM): the spike, and what it needs from the user

Spec 2026-10-08-0157 §9 (P3, "Arslan's workstation"): a macOS virtual machine on this Mac, made with Lume, running
its own Arslan Hands, so long foreground work happens there and nothing moves on the user's screen. **None of it is
built.** It is not in 0.1.60. This is the plan for the spike that comes first; the spec's order is spike →
addendum (the user approves it) → build.

## What the spike answers

The spec's list, measured on this Mac:
1. How long creating the VM takes, and how much disk it uses.
2. Idle memory and CPU with the VM running and nothing happening.
3. The permissions inside the VM: Arslan Hands needs Accessibility there too, granted once by the user in the VM.
4. The channel from Arslan on the Mac to the Hands in the VM: latency of a look and an action, and how Hands' peer
   check (it accepts only a signed Arslan) holds across the VM boundary.
5. Signing in to iCloud inside the VM (the user does it; Arslan never types passwords).

Plus one this spike adds: whether the user's apps behave in the VM as the plan assumes (Notes with the same iCloud
account, Finder on a shared `~/Arslan`).

## This Mac (2026-10-11)

Apple silicon, macOS 26.6.2, 48 GB memory, **106 GB free disk**.

## What gets installed and downloaded (each needs the user's yes)

| What | From | Size | Notes |
| --- | --- | --- | --- |
| Lume 0.6.1 | `trycua/cua`, `libs/lume` (installer: `https://cua.ai/lume/install.sh`) | small (a CLI) | MIT (the repository's root `LICENSE.md`, "Copyright (c) 2025 Cua AI, Inc."; `libs/lume` has no licence of its own). The installer script is read before it runs, and the version is pinned. |
| macOS restore image (Tahoe) | Apple (the URL `lume ipsw` prints) | read from the URL before downloading; Apple's restore images run to many GB (estimate 15–20 GB, not measured) | Downloaded once, to a folder the user picks |
| The VM's disk | created locally | up to 50 GB (Lume's guide: "50 GB free per macOS guest plus its restore image") | After it: roughly 35–40 GB free on this Mac |

Not used, by the spec: Cua Spaces and `cua-spacesd` (FSL-1.1-MIT, not open source).

## Things to change from Lume's defaults

- **Telemetry**: Lume's telemetry is on by default (pseudonymous installation events). Turned off before the first run:
  `lume config telemetry disable` (or `LUME_TELEMETRY_ENABLED=0`).
- **The guest account**: Lume's `tahoe` preset makes user `lume` with password `lume`, SSH on, autologin, no sleep or
  screen lock. The password is changed before anything else is put in the VM. The VM's network stays NAT (reachable
  from this Mac only).

## What only the user can do

1. Say yes to installing Lume and to the download (name, source, size as above).
2. Read Apple's macOS licence on virtual machines. The spec notes that it allows up to two additional macOS instances
   in VMs on a Mac already running macOS, including for personal non-commercial use; the user reads it first.
3. Inside the VM: allow Accessibility for Arslan Hands (one click in System Settings), and sign in to iCloud if Notes
   and other apps should see their own data.
4. About 30 minutes at the Mac for the steps above; the rest of the spike runs alone.

## After the spike

An addendum to the spec with the measurements and a build plan, for the user's approval. Rough shape of the build, to
be confirmed by the spike: a Hands in the VM, a channel from the Mac's Arslan to it, "在工作机上做" as a choice for a
background job, the VM's screen in a window to watch, and "我来接手" by clicking into it.
