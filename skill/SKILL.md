---
name: campsite-watcher
description: >
  Set up, configure, and health-check open-campsite-watcher in plain English.
  Use when the user wants to watch recreation.gov for campsite cancellations —
  e.g. "watch Upper Pines for July 3 and 4", "add Tuolumne Meadows to my
  watcher", "narrow the dates to just the weekend", "stop watching", "is the
  campsite watcher alive?", "did anything open up?". Translates natural-language
  requests into config.json edits and runs the watcher / health scripts.
---

# campsite-watcher — natural-language campsite cancellation watcher

This skill drives [open-campsite-watcher](https://github.com/Pdesolmi/open-campsite-watcher):
a zero-dependency Python watcher that polls recreation.gov and pings the user on
Telegram when a sold-out site frees up. Your job is to turn what the user says
into `config.json` and to run the scripts — the user should never have to edit
JSON or remember `launchctl` syntax.

## Files (relative to the repo root)

| File | Role |
|---|---|
| `config.json` | Where/when to watch. **You edit this.** Gitignored. |
| `.env` | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. Never print or commit. |
| `campsite_watcher.py` | The poller. Run with `--dry-run` to preview without sending. |
| `campsite_health.py` | Status check. Run to answer "is it alive?". |
| `config.example.json` | Reference shape if `config.json` doesn't exist yet. |

## Core rules

- **Always preview before writing `config.json`.** Show the user the resolved
  campgrounds + nights and confirm, then write.
- **Resolve campground IDs, don't guess.** If the user names a campground you
  don't have an ID for, ask them for the recreation.gov URL (the trailing number
  is the ID) or look it up — never invent an ID.
- **Convert relative dates to absolute** ISO `YYYY-MM-DD` using today's date.
- **Narrow, don't over-watch.** If the user already holds some nights, only
  watch the gap — extra nights just create noise.
- **Never reveal `.env` contents.**

## Intents

### SET_UP (first run)
1. Read `config.example.json` for the shape.
2. Ask for: campground(s), the exact nights, and a trip-end date (for
   `expire_after`).
3. Preview → write `config.json`.
4. If `.env` is missing, walk them through @BotFather (token) and getUpdates
   (chat id); have them paste the values, write `.env`.
5. `python3 campsite_watcher.py --dry-run` to prove it fetches.
6. Offer to schedule it (launchd template under `launchd/`).

### EDIT_WATCH ("watch X", "add/remove a campground", "narrow dates")
1. Load current `config.json`.
2. Apply the change to `campgrounds` / `nights` / `expire_after`.
3. Preview the diff → confirm → write.
4. Run `--dry-run` to confirm it still fetches cleanly.

### HEALTH ("is it alive?", "did anything open?")
Run `python3 campsite_health.py` and relay concisely:
the status emoji, last run time, last fetch counts, and **loudly surface any
currently-available site** (that's a live spot the user can still grab).

### STOP ("stop watching", "trip's over")
Set `expire_after` to now (or unload the launchd job if the user asks). Confirm
first.

## Day-of-week sanity check

A recreation.gov reservation of "Check In Jul 2 → Check Out Jul 3" means the
user **sleeps the night of Jul 2**. When discussing nights, state the weekday
explicitly so there's no off-by-one ("Jul 2 = Thursday night"). Watch the
**check-in date**, not the check-out date.
