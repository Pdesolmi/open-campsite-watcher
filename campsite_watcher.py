#!/usr/bin/env python3
"""Watch recreation.gov for campsite cancellations and alert via Telegram.

Config-driven, zero dependencies (Python 3.9+ stdlib only). Point it at one or
more campgrounds and the exact nights you need; it polls the public
availability API and pings you the moment a site frees up, with a direct
Add-to-Cart link.

Usage:
    python3 campsite_watcher.py [--config config.json] [--dry-run]
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def log(cfg: dict, msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    try:
        with Path(cfg["log_file"]).open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    nights = cfg["nights"]
    cfg["target_keys"] = [f"{d}T00:00:00Z" for d in nights]
    cfg["night_label"] = {}
    months = set()
    for d in nights:
        y, m, day = (int(x) for x in d.split("-"))
        cfg["night_label"][f"{d}T00:00:00Z"] = f"{MONTH_ABBR[m]} {day}"
        months.add(f"{y:04d}-{m:02d}-01T00:00:00.000Z")
    cfg["months"] = sorted(months)
    cfg.setdefault("max_repeats", 3)
    cfg.setdefault("poll_seconds", 120)
    cfg.setdefault("request_delay", 0.4)
    cfg["state_file"] = str(HERE / cfg.get("state_file", "state.json"))
    cfg["log_file"] = str(HERE / cfg.get("log_file", "watch.log"))
    return cfg


def telegram_send(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "disable_web_page_preview": "true", "parse_mode": "HTML",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=15) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"telegram err: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def fetch_campground(cfg: dict, cg_id: str, month_iso: str) -> dict | None:
    q = urllib.parse.quote(month_iso, safe="")
    url = (f"https://www.recreation.gov/api/camps/availability/"
           f"campground/{cg_id}/month?start_date={q}")
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        log(cfg, f"fetch {cg_id} {month_iso[:7]} err: {type(e).__name__}: {e}")
        return None


def current_available(cfg: dict) -> dict:
    found = {}
    fetched = []
    target_keys = cfg["target_keys"]
    for cg_id, cg_name in cfg["campgrounds"].items():
        site_count = 0
        failed = False
        for month_iso in cfg["months"]:
            data = fetch_campground(cfg, cg_id, month_iso)
            if not data:
                failed = True
                continue
            sites = data.get("campsites", {})
            site_count = max(site_count, len(sites))
            for site in sites.values():
                av = site.get("availabilities", {})
                nights = [n for n in target_keys if av.get(n) == "Available"]
                if not nights:
                    continue
                site_name = site.get("site", "?")
                key = f"{cg_id}:{site_name}"
                entry = found.setdefault(key, {
                    "cg_id": cg_id, "cg_name": cg_name, "site": site_name,
                    "campsite_id": site.get("campsite_id", ""),
                    "loop": site.get("loop", ""),
                    "type": site.get("campsite_type", ""),
                    "nights": [],
                })
                for n in nights:
                    label = cfg["night_label"][n]
                    if label not in entry["nights"]:
                        entry["nights"].append(label)
            time.sleep(cfg["request_delay"])
        fetched.append(f"{cg_name}:{'FETCH_FAILED' if failed else str(site_count)+'sites'}")
    log(cfg, "fetch ok: " + " ".join(fetched))
    return found


def build_message(cfg: dict, new_items: list[dict]) -> str:
    title = cfg.get("title", "Campsite").upper()
    lines = [f"\U0001f3d5️ <b>{html.escape(title)} — spot(s) opened!</b>", ""]
    by_cg: dict[str, list] = {}
    for it in new_items:
        by_cg.setdefault(it["cg_name"], []).append(it)
    for cg_name, items in by_cg.items():
        lines.append(f"<b>{html.escape(cg_name)}</b>")
        for it in items:
            loop = f" · loop {html.escape(it['loop'])}" if it["loop"] else ""
            t = f" · {html.escape(it['type'])}" if it["type"] else ""
            n = it.get("alert_count", 1)
            rep = f"  \U0001f501 still open · ping {n}/{cfg['max_repeats']}" if n > 1 else ""
            lines.append(f"  • Site {html.escape(str(it['site']))}{loop}{t} "
                         f"→ {', '.join(it['nights'])}{rep}")
            if it.get("campsite_id"):
                site_url = (f"https://www.recreation.gov/camping/campsites/"
                            f"{it['campsite_id']}")
                lines.append(f'    \U0001f449 <a href="{site_url}">TAP → Add to Cart '
                             f'(site {html.escape(str(it["site"]))})</a>')
        lines.append("")
    lines.append("⚡ Add to Cart holds it ~15 min. Tap the site link, pick the "
                 "night, Add to Cart, then pay. Be logged in already.")
    return "\n".join(lines)


def expired(cfg: dict) -> bool:
    exp = cfg.get("expire_after")
    if not exp:
        return False
    return datetime.now(timezone.utc) >= datetime.fromisoformat(
        exp.replace("Z", "+00:00"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))

    if expired(cfg):
        log(cfg, "EXPIRED (past expire_after) — stopping")
        label = cfg.get("launchd_label")
        plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        if label and plist.exists():
            os.system(f"launchctl unload {plist} 2>/dev/null")
        return 0

    env = load_env(HERE / ".env")
    token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log(cfg, "missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (see .env.example)")
        return 1

    state_file = Path(cfg["state_file"])
    prev = {}
    if state_file.exists():
        try:
            prev = json.loads(state_file.read_text()).get("available", {})
        except Exception:
            prev = {}

    current = current_available(cfg)

    to_alert = []
    for key, item in current.items():
        prev_count = prev.get(key, {}).get("alert_count", 0)
        if prev_count < cfg["max_repeats"]:
            item["alert_count"] = prev_count + 1
            to_alert.append(item)
        else:
            item["alert_count"] = prev_count

    if to_alert:
        msg = build_message(cfg, to_alert)
        if args.dry_run:
            log(cfg, f"DRY-RUN would alert {len(to_alert)} site(s)")
            print("\n" + msg)
            ok = True
        else:
            ok = telegram_send(token, chat_id, msg)
        log(cfg, f"ALERT {len(to_alert)} site(s) sent={ok}: "
            f"{[it['cg_name']+'/'+str(it['site'])+'#'+str(it['alert_count']) for it in to_alert]}")
    else:
        log(cfg, f"no new availability (current={len(current)} known sites avail)")

    state_file.write_text(json.dumps({
        "available": current,
        "updated": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
