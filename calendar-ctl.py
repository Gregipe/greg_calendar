#!/usr/bin/env python3
"""
Calendar Controller — CLI for Greg's personalized calendar.
Read/write/query ~/.hermes/calendar-data.json (local) or GitHub repo.

Usage:
  python3 calendar-ctl.py read [--date YYYY-MM-DD] [--week] [--cloud]
  python3 calendar-ctl.py add --date YYYY-MM-DD --start HH:MM --end HH:MM --title "..." --tier 🔴 [--notes "..." --hunai] [--cloud]
  python3 calendar-ctl.py edit --id bl_XXX [--title "..." --tier 🔴 --start HH:MM --end HH:MM --notes "..."] [--cloud]
  python3 calendar-ctl.py delete --id bl_XXX [--cloud]
  python3 calendar-ctl.py auto-recovery --date YYYY-MM-DD [--minutes 15] [--cloud]
  python3 calendar-ctl.py report [--cloud]
  python3 calendar-ctl.py next-recovery [--cloud]
  python3 calendar-ctl.py export [--path output.json]
  python3 calendar-ctl.py import --path input.json [--cloud]

Use --cloud to read/write directly from the GitHub repo (requires token in CALENDAR_GITHUB_TOKEN env var).
"""

import json, sys, os, base64, uuid
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CALENDAR_PATH = os.path.expanduser("~/.hermes/calendar-data.json")
GITHUB_TOKEN = os.environ.get("CALENDAR_GITHUB_TOKEN", "")
GITHUB_OWNER = "Gregipe"
GITHUB_REPO = "greg_calendar"
DATA_PATH = "calendar-data.json"
API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{DATA_PATH}"

def github_fetch():
    if not GITHUB_TOKEN:
        return None
    req = Request(API_BASE, headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"})
    try:
        resp = urlopen(req)
        data = json.loads(resp.read())
        content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")
        return {"sha": data["sha"], "content": json.loads(content)}
    except HTTPError as e:
        if e.code == 404:
            return {"sha": None, "content": None}
        print(f"GitHub fetch error {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return None

def github_push(data_obj, sha=None):
    if not GITHUB_TOKEN:
        return False
    body = json.dumps({
        "message": f"Calendar update {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": base64.b64encode(json.dumps(data_obj, indent=2, ensure_ascii=False).encode()).decode(),
        "sha": sha or None
    }).encode()
    req = Request(API_BASE, data=body, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    }, method="PUT")
    try:
        resp = urlopen(req)
        return True
    except HTTPError as e:
        print(f"GitHub push error {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return False

def load(use_cloud=False):
    if use_cloud and GITHUB_TOKEN:
        result = github_fetch()
        if result and result["content"]:
            return result["content"]
        print("⚠️ Cloud fetch failed, falling back to local", file=sys.stderr)
    with open(CALENDAR_PATH) as f:
        return json.load(f)

def save(data, use_cloud=False):
    data["lastUpdated"] = datetime.now().isoformat(timespec="seconds")
    # Always save locally
    with open(CALENDAR_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    # Optionally push to cloud
    if use_cloud and GITHUB_TOKEN:
        result = github_fetch()
        sha = result["sha"] if result and result.get("sha") else None
        github_push(data, sha)

def gen_id(): return "bl_" + uuid.uuid4().hex[:8]
def time_to_min(t): h, m = map(int, t.split(":")); return h * 60 + m
def min_to_time(m): return f"{m//60:02d}:{m%60:02d}"
def slot_round_up(t): return min_to_time(((time_to_min(t) + 14) // 15) * 15)
def slot_round_down(t): return min_to_time((time_to_min(t) // 15) * 15)

def cmd_read(args, use_cloud):
    data = load(use_cloud)
    date_key = args.get("--date")
    if date_key:
        day_data = data.get("days", {}).get(date_key)
        if not day_data:
            print(f"No blocks scheduled for {date_key}")
            return
        print(f"\n{'='*60}")
        print(f"  📅  {date_key}")
        notes = day_data.get("notes", "")
        if notes: print(f"  {notes}")
        print(f"{'='*60}")
        blocks = sorted(day_data.get("blocks", []), key=lambda b: b["start"])
        for b in blocks:
            dur = time_to_min(b["end"]) - time_to_min(b["start"])
            print(f"  {b['start']}–{b['end']} ({dur:3d}min) {b['tier']}  {b['title']}")
            if b.get("notes"): print(f"          └─ {b['notes']}")
        print()
    elif args.get("--week"):
        d = datetime.strptime(args["--date"], "%Y-%m-%d") if args.get("--date") else datetime.now()
        monday = d - timedelta(days=d.weekday())
        for i in range(7): cmd_read({"--date": (monday + timedelta(days=i)).strftime("%Y-%m-%d")}, use_cloud)
    else:
        days = sorted(data.get("days", {}).keys())
        print(f"\n📆 Calendar — {len(days)} scheduled days (last updated: {data.get('lastUpdated','N/A')})\n")
        for d in days[-14:]:
            day_data = data["days"][d]
            bc = len(day_data.get("blocks", []))
            note = f" — {day_data.get('notes', '')}" if day_data.get("notes") else ""
            print(f"  {d}  ({bc} blocks){note}")

def cmd_add(args, use_cloud):
    date_key = args.get("--date")
    if not date_key: print("--date required"); return
    data = load(use_cloud)
    start = slot_round_up(args.get("--start", "09:00"))
    end = slot_round_down(args.get("--end", "10:00"))
    title = args.get("--title", "New block")
    tier = args.get("--tier", "🟡")
    notes = args.get("--notes", "")
    if args.get("--hunai"):
        prefix = data.get("settings", {}).get("hunaiPrefix", "Hunar.ai : ")
        if not title.startswith(prefix): title = prefix + title
    if date_key not in data["days"]: data["days"][date_key] = {"blocks": [], "notes": ""}
    block = {"id": gen_id(), "start": start, "end": end, "title": title, "tier": tier, "notes": notes}
    data["days"][date_key]["blocks"].append(block)
    save(data, use_cloud)
    print(f"✅ Added: {start}–{end} {tier} {title}")

def cmd_edit(args, use_cloud):
    bl_id = args.get("--id")
    if not bl_id: print("--id required"); return
    data = load(use_cloud)
    found = False
    for day_key, day_data in data["days"].items():
        for b in day_data.get("blocks", []):
            if b["id"] == bl_id:
                if args.get("--title"): b["title"] = args["--title"]
                if args.get("--tier"): b["tier"] = args["--tier"]
                if args.get("--start"): b["start"] = slot_round_up(args["--start"])
                if args.get("--end"): b["end"] = slot_round_down(args["--end"])
                if args.get("--notes"): b["notes"] = args["--notes"]
                found = True
                print(f"✅ Updated: {b['start']}–{b['end']} {b['tier']} {b['title']} ({day_key})")
                break
    if not found: print(f"❌ Block {bl_id} not found")
    else: save(data, use_cloud)

def cmd_delete(args, use_cloud):
    bl_id = args.get("--id")
    if not bl_id: print("--id required"); return
    data = load(use_cloud)
    found = False
    for day_key, day_data in data["days"].items():
        for b in day_data["blocks"]:
            if b["id"] == bl_id:
                day_data["blocks"].remove(b)
                found = True
                print(f"🗑️ Deleted: {b['start']}–{b['end']} {b['tier']} {b['title']} ({day_key})")
                break
    if not found: print(f"❌ Block {bl_id} not found")
    else: save(data, use_cloud)

def cmd_autorecovery(args, use_cloud):
    date_key = args.get("--date", datetime.now().strftime("%Y-%m-%d"))
    rec_min = int(args.get("--minutes", 15))
    data = load(use_cloud)
    if date_key not in data["days"]: print(f"No blocks on {date_key}"); return
    blocks = sorted(data["days"][date_key].get("blocks", []), key=lambda b: b["start"])
    rec_tier = data.get("settings", {}).get("recoveryTier", "🔵")
    no_back = set(data.get("settings", {}).get("noBackToBack", ["🔴"]))
    added = 0; i = 0
    while i < len(blocks) - 1:
        curr, next_b = blocks[i], blocks[i+1]
        gap = time_to_min(next_b.start) - time_to_min(curr.end)
        violation = (curr["tier"] == next_b["tier"] and curr["tier"] in no_back)
        if (violation or gap > 15) and gap < rec_min + 5:
            rec_end = min_to_time(min(time_to_min(curr.end) + rec_min, time_to_min(next_b.start)))
            if time_to_min(rec_end) > time_to_min(curr.end):
                blocks.insert(i + 1, {"id": gen_id(), "start": min_to_time(time_to_min(curr.end)), "end": rec_end, "title": f"🔵 Recovery — {rec_min}min reset", "tier": rec_tier, "notes": ""})
                added += 1; i += 1
        i += 1
    data["days"][date_key]["blocks"] = blocks
    save(data, use_cloud)
    print(f"✅ Inserted {added} recovery blocks")

def cmd_next_recovery(args, use_cloud):
    data = load(use_cloud)
    now = datetime.now(); today = now.strftime("%Y-%m-%d"); now_min = now.hour * 60 + now.minute
    if today in data["days"]:
        for b in sorted(data["days"][today]["blocks"], key=lambda b: b["start"]):
            if b["tier"] == "🔵" and time_to_min(b["start"]) > now_min:
                print(f"🔄 Next recovery: {b['start']}–{b['end']} — {b['title']} ({time_to_min(b['start'])-now_min} min away)")
                return
        print("⏰ No more scheduled recovery today.")
    else: print("📭 No schedule today.")

def cmd_report(args, use_cloud):
    data = load(use_cloud)
    date_key = args.get("--date", datetime.now().strftime("%Y-%m-%d"))
    if date_key not in data["days"]: print(f"No schedule for {date_key}"); return
    blocks = sorted(data["days"][date_key]["blocks"], key=lambda b: b["start"])
    now_min = datetime.now().hour * 60 + datetime.now().minute
    current = None; upcoming = []
    print(f"\n📆 {date_key}\n{'─'*50}")
    for b in blocks:
        s, e = time_to_min(b["start"]), time_to_min(b["end"])
        status = ""
        if s <= now_min < e: status = " ◀ NOW"; current = b
        elif s > now_min: status = " ⏳"; upcoming.append(b)
        print(f"  {b['start']}–{b['end']} ({e-s:3d}min) {b['tier']}  {b['title']}{status}")
    if current:
        pct = int((now_min - time_to_min(current["start"])) / max(time_to_min(current["end"]) - time_to_min(current["start"]), 1) * 100)
        print(f"\n  🎯 Now: {current['title']} ({pct}% done)")
    if upcoming: print(f"  ⏩ Next: {upcoming[0]['start']} — {upcoming[0]['tier']} {upcoming[0]['title']}")

def cmd_export(args, _):
    data = load(False)
    path = args.get("--path", os.path.expanduser("~/.hermes/calendar-export.json"))
    with open(path, "w") as f: json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"📤 Exported to {path}")

def cmd_import(args, use_cloud):
    path = args.get("--path")
    if not path: print("--path required"); return
    with open(path) as f: imported = json.load(f)
    data = load(False)
    for day_key, day_data in imported.get("days", {}).items():
        if day_key in data["days"]:
            existing_ids = {b["id"] for b in data["days"][day_key].get("blocks", [])}
            for b in day_data.get("blocks", []):
                if b["id"] not in existing_ids: data["days"][day_key]["blocks"].append(b)
        else: data["days"][day_key] = day_data
    save(data, use_cloud)
    print(f"📥 Imported from {path}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args: print(__doc__); sys.exit(0)

    use_cloud = "--cloud" in args
    args_no_flag = [a for a in args if a != "--cloud"]

    cmd = args_no_flag[0] if args_no_flag else ""
    kwargs = {}
    i = 1
    while i < len(args_no_flag):
        if args_no_flag[i].startswith("--"):
            key = args_no_flag[i]
            if i + 1 < len(args_no_flag) and not args_no_flag[i+1].startswith("--"):
                kwargs[key] = args_no_flag[i+1]; i += 2
            else:
                kwargs[key] = True; i += 1
        else: i += 1

    commands = {
        "read": cmd_read, "add": cmd_add, "edit": cmd_edit, "delete": cmd_delete,
        "auto-recovery": cmd_autorecovery, "export": cmd_export, "import": cmd_import,
        "next-recovery": cmd_next_recovery, "report": cmd_report,
    }
    if cmd in commands:
        callback = commands[cmd]
        # Determine if this command needs use_cloud
        if cmd in ("export",): callback(kwargs, None)
        elif cmd in ("read","add","edit","delete","auto-recovery","import","next-recovery","report"):
            callback(kwargs, use_cloud)
    else:
        print(f"Unknown command: {cmd}"); print(__doc__)
