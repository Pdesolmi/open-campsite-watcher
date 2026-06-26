#!/usr/bin/env python3
"""Health check for the campsite watcher: is it loaded, running, and reaching
recreation.gov? Reads config.json for the launchd label and expiry.

Usage: python3 campsite_health.py [--config config.json]
"""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STALE_SECONDS = 360


def launchd_status(label: str) -> tuple[bool, str]:
    if not label:
        return False, "no launchd_label in config (run manually / via cron)"
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception as e:
        return False, f"launchctl error: {e}"
    for line in out.splitlines():
        if label in line:
            cols = line.split("\t")
            exit_code = cols[1] if len(cols) > 1 else "?"
            return True, f"loaded (last exit {exit_code})"
    return False, "NOT loaded"


def parse_log(log_file: Path):
    if not log_file.exists():
        return None, None, None
    last_ts = last_fetch = last_event = None
    for line in log_file.read_text().splitlines():
        m = re.match(r"(\S+) (.*)", line)
        if not m:
            continue
        ts, body = m.group(1), m.group(2)
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        last_ts = t
        if body.startswith("fetch ok:") or "FETCH_FAILED" in body:
            last_fetch = body
        if body.startswith(("ALERT", "no new availability", "EXPIRED")):
            last_event = body
    return last_ts, last_fetch, last_event


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.json"))
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"No config at {cfg_path}. Copy config.example.json → config.json first.")
        return
    cfg = json.loads(cfg_path.read_text())
    title = cfg.get("title", "Campsite")
    label = cfg.get("launchd_label", "")
    log_file = HERE / cfg.get("log_file", "watch.log")
    state_file = HERE / cfg.get("state_file", "state.json")
    exp_raw = cfg.get("expire_after")
    expire_after = (datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
                    if exp_raw else None)

    now = datetime.now(timezone.utc)
    print(f"\U0001f3d5️ {title} watcher health")
    print("=" * 34)

    if not log_file.exists():
        print("Status: ⚪ NOT INSTALLED (no log yet — never run?)")
        return

    loaded, ld_msg = launchd_status(label)
    last_ts, last_fetch, last_event = parse_log(log_file)

    is_expired = bool(expire_after and now >= expire_after)
    age = (now - last_ts).total_seconds() if last_ts else None
    fetch_ok = bool(last_fetch and "FETCH_FAILED" not in last_fetch
                    and "fetch ok" in last_fetch)

    if is_expired:
        status = "⚪ EXPIRED (past expire_after — watcher self-stopped)"
    elif loaded and age is not None and age <= STALE_SECONDS and fetch_ok:
        status = "🟢 HEALTHY"
    elif label and not loaded:
        status = "🔴 DOWN (launchd job not loaded)"
    elif age is not None and age > STALE_SECONDS:
        status = f"🟠 STALE (no run in {int(age//60)}m — machine asleep/offline?)"
    elif not fetch_ok:
        status = "🔴 FETCH FAILING (reaching recreation.gov broken)"
    else:
        status = "🟠 UNKNOWN"

    print(f"Status: {status}")
    print(f"launchd: {ld_msg}")
    if last_ts:
        print(f"Last run: {last_ts.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')} "
              f"({int(age // 60)}m{int(age % 60)}s ago)")
    else:
        print("Last run: never logged")
    if last_fetch:
        print(f"Last fetch: {last_fetch}")
    if last_event:
        print(f"Last result: {last_event}")

    if state_file.exists():
        try:
            avail = json.loads(state_file.read_text()).get("available", {})
            print(f"Currently available sites tracked: {len(avail)}")
            for v in list(avail.values())[:8]:
                print(f"   • {v['cg_name']} site {v['site']} → {', '.join(v['nights'])}")
        except Exception:
            pass

    if expire_after and not is_expired:
        days_left = (expire_after - now).total_seconds() / 86400
        print(f"Auto-stops in: {days_left:.1f} days")


if __name__ == "__main__":
    main()
