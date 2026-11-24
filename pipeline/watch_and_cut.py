"""Cut every short whose voice recording has arrived.

A short folder is ready when it has spec.json, gathered assets
(assets/.done) and a voice file named <Short ID>.m4a / .mp3 / .wav, but no
<Short ID>.mp4 newer than the voice file. For each one:
  download everything -> run the engine -> upload <ID>.mp4 and <ID>.qa.json
  -> Post log: Status "Recorded" + a Notes line -> Telegram: the video (or
  its Drive link if over 50 MB) and the platform captions.
Nothing is ever posted to YouTube, Instagram or TikTok.

To re-cut: upload a new voice file (or delete <ID>.mp4).
If a cut fails, <ID>.error.txt is saved; delete it (or upload the voice
again) to retry.

Run:  python -m pipeline.watch_and_cut           (cut what is ready)
      python -m pipeline.watch_and_cut --check   (only report; no cutting)
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
import traceback
from zoneinfo import ZoneInfo

from . import google_io as g, telegram

POST_LOG = "Post log"
VOICE_EXT = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac")
DONE = ".done"


# ---------------------------------------------------------------- state

def find_voice(short_id, children):
    """The newest file named <Short ID>.<audio extension> (any letter case)."""
    found = [c for c in children
             if os.path.splitext(c["name"])[1].lower() in VOICE_EXT
             and os.path.splitext(c["name"])[0].strip().lower()
             == short_id.lower()]
    return max(found, key=lambda c: c.get("modifiedTime", ""), default=None)


def cut_state(short_id, children, asset_children=None):
    """What a short folder is waiting for. One of:
    no_spec, waiting_voice, failed_before, done, check_assets (call again
    with asset_children), waiting_assets, ready."""
    files = g.by_name(children)
    if "spec.json" not in files:
        return "no_spec"
    voice = find_voice(short_id, children)
    if not voice:
        return "waiting_voice"
    stamp = voice.get("modifiedTime", "")
    error = files.get(f"{short_id}.error.txt")
    if error and error.get("modifiedTime", "") >= stamp:
        return "failed_before"
    video = files.get(f"{short_id}.mp4")
    if video and video.get("modifiedTime", "") >= stamp:
        return "done"
    if asset_children is None:
        return "check_assets"
    if DONE not in {c["name"] for c in asset_children}:
        return "waiting_assets"
    return "ready"


def map_assets(spec, assets_dir):
    """Point each line's "asset" at its downloaded file. Returns the line
    numbers (1-based) that will show a placeholder instead."""
    placeholders = []
    for n, line in enumerate(spec.get("lines", []), 1):
        if (line.get("shot") or "").upper() == "TEXT":
            continue
        name = line.get("asset_file")
        path = os.path.join(assets_dir, name) if name else None
        if path and os.path.exists(path):
            line["asset"] = os.path.abspath(path)
        else:
            line.pop("asset", None)
            placeholders.append(n)
    return placeholders


# ---------------------------------------------------------------- messages

def failed_checks(report):
    return [k for k, v in report.get("checks", {}).items()
            if not v and k != "all_assets_real"]


def caption_text(short_id, spec, report, placeholders, link=None):
    title = " - ".join(x for x in (short_id, spec.get("topic", "")) if x)
    if report.get("passed"):
        qa = "QA passed."
    else:
        qa = "QA FAILED: " + ", ".join(failed_checks(report)) + \
             ". Check it carefully before posting."
    parts = [title, f"{report.get('duration_s', '?')} s. {qa}"]
    if placeholders:
        parts.append("Placeholder visuals on line(s) "
                     + ", ".join(map(str, placeholders)) + ".")
    if link:
        parts.append(f"Too big for Telegram, watch it here: {link}")
    parts.append("Nothing was posted. Review it, then post it yourself.")
    return "\n".join(parts)


def _as_text(value):
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_as_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def platform_messages(spec):
    """One ready-to-copy message per platform from spec["platform_copy"]."""
    copy = spec.get("platform_copy")
    if not copy:
        return []
    if isinstance(copy, dict):
        return [f"{platform.upper()}\n\n{_as_text(text)}"
                for platform, text in copy.items() if text]
    return [_as_text(copy)]


def post_text(short_id, spec, report, placeholders):
    """Everything needed to post, as one file saved next to the video."""
    sections = [caption_text(short_id, spec, report, placeholders)]
    sections += platform_messages(spec)
    return "\n\n----------\n\n".join(sections) + "\n"


# ---------------------------------------------------------------- tracker

def today():
    tz = os.environ.get("LOCAL_TIMEZONE", "Europe/Berlin")
    return datetime.datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")


def update_post_log(sheets, sheet_id, short_id, passed, date):
    """Status -> Recorded (never undoes Posted/Dropped); add a Notes line."""
    rows = g.read_tab(sheets, sheet_id, POST_LOG, "A:X")
    row = g.find_row(rows, short_id)
    if not row:
        print(f"[cut] {short_id} is not in the Post log; sheet not updated")
        return None
    updates = {}
    if g.cell(rows, row, "K").strip().lower() not in ("posted", "dropped"):
        updates["K"] = "Recorded"
    note = f"Rendered {date}, QA {'passed' if passed else 'failed'}"
    old = g.cell(rows, row, "X").strip()
    updates["X"] = f"{old}\n{note}" if old else note
    g.update_cells(sheets, sheet_id, POST_LOG, row, updates)
    return row


# ---------------------------------------------------------------- cut one

def cut_short(drive, sheets, sheet_id, folder, children, asset_children,
              tmp):
    from engine.render import render  # heavy imports only when cutting

    short_id = folder["name"]
    files = g.by_name(children)
    spec = g.read_json(drive, files["spec.json"])
    voice = find_voice(short_id, children)
    voice_local = os.path.join(tmp, "voice" +
                               os.path.splitext(voice["name"])[1].lower())
    g.download_file(drive, voice["id"], voice_local)

    assets_dir = os.path.join(tmp, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    asset_files = g.by_name(asset_children)
    for name in {l.get("asset_file") for l in spec.get("lines", [])} - {None}:
        if name in asset_files:
            g.download_file(drive, asset_files[name]["id"],
                            os.path.join(assets_dir, name))
    placeholders = map_assets(spec, assets_dir)

    spec_path = os.path.join(tmp, "spec.json")
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False)
    out = os.path.join(tmp, f"{short_id}.mp4")
    report = render(spec_path, voice_local, out,
                    workdir=os.path.join(tmp, "work"))
    report["placeholder_lines"] = placeholders
    qa_path = os.path.join(tmp, f"{short_id}.qa.json")
    with open(qa_path, "w") as fh:
        json.dump(report, fh, indent=1)

    video_item = g.upload_file(drive, folder["id"], out, children=children)
    g.upload_file(drive, folder["id"], qa_path, children=children,
                  mime="application/json")
    # Titles and captions sit beside the video, so posting works from the
    # Drive app alone (Telegram is optional).
    g.upload_text(drive, folder["id"], f"{short_id}.post.txt",
                  post_text(short_id, spec, report, placeholders), tmp,
                  children=children)
    update_post_log(sheets, sheet_id, short_id, report["passed"], today())

    sent = telegram.send_video(out, caption_text(short_id, spec, report,
                                                 placeholders))
    if not sent:
        telegram.send_message(caption_text(
            short_id, spec, report, placeholders,
            link=video_item.get("webViewLink", "(see the Drive folder)")))
    for message in platform_messages(spec):
        telegram.send_message(message)
    return report


def record_failure(drive, folder, children, tmp, error_text):
    short_id = folder["name"]
    try:
        g.upload_text(drive, folder["id"], f"{short_id}.error.txt",
                      error_text[-3000:], tmp, children=children)
    except Exception:
        traceback.print_exc()
    last = error_text.strip().splitlines()[-1] if error_text.strip() else "?"
    telegram.send_message(
        f"{short_id}: the cut FAILED ({last[:300]}).\nTo try again, delete "
        f"{short_id}.error.txt in Drive or upload the voice file again.")


# ---------------------------------------------------------------- main

def scan(drive, root):
    """Yield (folder, children, asset_children, state) for every short."""
    for folder in sorted(g.list_folders(drive, root), key=lambda f: f["name"]):
        children = g.list_children(drive, folder["id"])
        state = cut_state(folder["name"], children)
        assets = []
        if state == "check_assets":
            sub = next((c for c in children
                        if c["name"] == "assets" and g.is_folder(c)), None)
            assets = g.list_children(drive, sub["id"]) if sub else []
            state = cut_state(folder["name"], children, assets)
        yield folder, children, assets, state


def main(argv=None):
    p = argparse.ArgumentParser(description="Cut shorts whose voice arrived.")
    p.add_argument("--check", action="store_true",
                   help="only report which shorts are ready")
    args = p.parse_args(argv)
    root = g.require_env("DRIVE_ROOT_FOLDER_ID")
    drive, sheets = g.services()

    if args.check:
        ready = 0
        for folder, _, _, state in scan(drive, root):
            print(f"[cut] {folder['name']}: {state}")
            ready += state == "ready"
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as fh:
                fh.write(f"needed={'true' if ready else 'false'}\n")
        return 0

    sheet_id = g.require_env("TRACKER_SHEET_ID")
    failures = 0
    for folder, children, assets, state in scan(drive, root):
        print(f"[cut] {folder['name']}: {state}")
        if state != "ready":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                report = cut_short(drive, sheets, sheet_id, folder, children,
                                   assets, tmp)
                print(f"[cut] {folder['name']}: done, QA "
                      f"{'passed' if report['passed'] else 'FAILED'}")
            except Exception:
                failures += 1
                text = traceback.format_exc()
                print(text)
                record_failure(drive, folder, children, tmp, text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
