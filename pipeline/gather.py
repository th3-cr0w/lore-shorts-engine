"""Gather the visuals for every short that has a spec.json but no assets yet.

For each short folder in Drive ("Lore Shorts/<Short ID>/"):
  ART lines   -> open-licence image from the museum named in the Art bank
  STOCK / SIL -> a Pexels stock clip found with the line's search terms
  TEXT lines  -> nothing (the engine draws the text)
Files land in "<Short ID>/assets/" with a licences.csv, each line's file name
is written into spec.json as "asset_file", and an "assets/.done" marker says
the short is finished. Safe to run again: anything already there is reused.

To redo a short: delete assets/.done (and any file you want replaced).
To use your own visual for line 3: put 03.jpg or 03.mp4 in assets/ first.

Run:  python -m pipeline.gather
"""
import csv
import io
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field

import requests
from PIL import Image

from . import art_sources, google_io as g, http, pexels, telegram

ART_TAB = "Art bank"
ART_COLS = {"ID": "A", "Artist": "B", "Title": "C", "Rights check": "G",
            "Link": "H", "Status": "L"}
DONE = ".done"
LICENCES = "licences.csv"
LICENCE_FIELDS = ["file", "line", "shot", "source", "source_id", "page",
                  "download_url", "creator", "licence", "credit_required"]
MAX_ATTEMPTS = 3  # after this many runs with network errors, stop retrying
PEXELS_LICENCE = "Pexels License (free to use, credit appreciated)"


class Skip(art_sources.Skip):
    pass


# ---------------------------------------------------------------- state

READY_STATUSES = {"checked", "recorded", "posted"}


def lore_checked(post_rows, short_id):
    """Gather only after the lore check: the short's Post log Status must be
    Checked (or later). Shorts with no Post log row are left alone."""
    row = g.find_row(post_rows, short_id)
    if row is None:
        return False
    return g.cell(post_rows, row, "K").strip().lower() in READY_STATUSES


def wants_asset(line):
    """TEXT lines get a background only when they name an Art bank work."""
    return (line.get("shot") or "").upper() != "TEXT" or bool(line.get("art_id"))


def needs_gather(children, asset_children):
    """True if the short has a spec.json and its assets are not done yet."""
    if "spec.json" not in {c["name"] for c in children}:
        return False
    return DONE not in {c["name"] for c in (asset_children or [])}


def find_existing(names, stem):
    """A file in assets/ called <stem>.<anything> (not a depth map)."""
    for name in sorted(names):
        base, _ = os.path.splitext(name)
        if base.lower() == stem.lower():
            return name
    return None


# ---------------------------------------------------------------- Art bank

class ArtBank:
    """The Art bank tab, read once per run."""

    def __init__(self, sheets, sheet_id):
        self.sheets, self.sheet_id = sheets, sheet_id
        self.rows = g.read_tab(sheets, sheet_id, ART_TAB, "A:L")

    def get(self, art_id):
        row = g.find_row(self.rows, art_id)
        if not row:
            return None
        info = {k: g.cell(self.rows, row, col) for k, col in ART_COLS.items()}
        info["row"] = row
        return info

    def nga_ids(self):
        ids = set()
        for row in self.rows[1:]:
            link = row[7] if len(row) > 7 else ""
            kind, key = art_sources.classify(link)
            if kind == "nga":
                ids.add(key)
        return ids

    def set_status(self, art_id, status):
        row = g.find_row(self.rows, art_id)
        if not row:
            return
        g.update_cells(self.sheets, self.sheet_id, ART_TAB, row,
                       {ART_COLS["Status"]: status})
        line = self.rows[row - 1]
        line.extend([""] * (12 - len(line)))
        line[11] = status


# ---------------------------------------------------------------- files

def save_image(src, dest, cap=art_sources.CAP):
    """Open any image, shrink it so the longest side is at most cap, and
    save it as a high-quality JPEG."""
    Image.MAX_IMAGE_PIXELS = 400_000_000  # museum scans can be very large
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((cap, cap), Image.LANCZOS)
        im.save(dest, "JPEG", quality=92)
    return dest


def licences_to_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=LICENCE_FIELDS,
                            extrasaction="ignore")
    writer.writeheader()
    for name in sorted(rows):
        writer.writerow(rows[name])
    return buf.getvalue()


def csv_to_licences(text):
    return {r["file"]: r for r in csv.DictReader(io.StringIO(text))
            if r.get("file")}


def _definitive(exc):
    """Errors that will not fix themselves by trying again (e.g. 404)."""
    if isinstance(exc, (Skip, art_sources.Skip)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        return 400 <= code < 500 and code != 429
    return isinstance(exc, (ValueError, OSError)) and \
        not isinstance(exc, requests.RequestException)


@dataclass
class Ctx:
    drive: object
    art_bank: object
    workdir: str
    pexels_key: str = ""
    nga_ids: set = field(default_factory=set)
    # per short, set by gather_short:
    assets_id: str = ""
    asset_items: list = field(default_factory=list)
    names: set = field(default_factory=set)
    licences: dict = field(default_factory=dict)
    used_videos: set = field(default_factory=set)


def _upload(ctx, local, name):
    item = g.upload_file(ctx.drive, ctx.assets_id, local, name=name,
                         children=ctx.asset_items)
    ctx.asset_items.append(item)
    ctx.names.add(name)


# ---------------------------------------------------------------- per line

def get_art(ctx, n, line):
    art_id = (line.get("art_id") or "").strip()
    if not art_id:
        raise Skip("ART line has no art_id")
    existing = find_existing(ctx.names, art_id)
    if existing:
        return existing
    row = ctx.art_bank.get(art_id)
    if not row:
        raise Skip(f"{art_id} is not in the Art bank")
    if row["Status"].strip().lower() == "rejected":
        raise Skip(f"{art_id} is marked Rejected in the Art bank")
    if row["Rights check"].strip().lower().startswith("check"):
        raise Skip(f"{art_id} rights still need checking "
                   f"({row['Rights check']})")
    info = art_sources.resolve(row["Link"], ctx.nga_ids)

    raw = os.path.join(ctx.workdir, f"{art_id}.download")
    urls = [info["url"]] + ([info["fallback_url"]]
                            if info.get("fallback_url") else [])
    for i, url in enumerate(urls):
        try:
            http.download(url, raw)
            break
        except Exception:
            if i == len(urls) - 1:
                raise
    name = f"{art_id}.jpg"
    local = os.path.join(ctx.workdir, name)
    save_image(raw, local)
    _upload(ctx, local, name)
    ctx.licences[name] = {
        "file": name, "line": n, "shot": "ART", "source": info["source"],
        "source_id": art_id, "page": row["Link"], "download_url": info["url"],
        "creator": info.get("credit") or row["Artist"],
        "licence": info["licence"],
        "credit_required": "yes" if info.get("credit_required") else "no"}
    if row["Status"].strip().lower() in ("", "unused"):
        ctx.art_bank.set_status(art_id, "Downloaded")
    return name


def get_stock(ctx, n, line):
    if not ctx.pexels_key:
        raise Skip("PEXELS_API_KEY is not set")
    video, file = pexels.find_clip(line, ctx.pexels_key, ctx.used_videos)
    if not video:
        raise Skip("no suitable Pexels clip for: "
                   + ", ".join(line.get("query") or []))
    name = f"{n:02d}.mp4"
    local = os.path.join(ctx.workdir, name)
    http.download(file["link"], local)
    _upload(ctx, local, name)
    ctx.used_videos.add(video["id"])
    user = video.get("user") or {}
    ctx.licences[name] = {
        "file": name, "line": n, "shot": line.get("shot", "STOCK").upper(),
        "source": "Pexels", "source_id": video["id"],
        "page": video.get("url", ""), "download_url": file["link"],
        "creator": f"{user.get('name', '')} {user.get('url', '')}".strip(),
        "licence": PEXELS_LICENCE, "credit_required": "no"}
    return name


# ---------------------------------------------------------------- per short

def gather_short(ctx, folder, children):
    """Gather one short. Returns a dict summary."""
    files = g.by_name(children)
    spec = g.read_json(ctx.drive, files["spec.json"])
    ctx.assets_id = g.ensure_folder(ctx.drive, folder["id"], "assets", children)
    ctx.asset_items = g.list_children(ctx.drive, ctx.assets_id)
    ctx.names = {i["name"] for i in ctx.asset_items if not g.is_folder(i)}
    ctx.licences = {}
    if LICENCES in ctx.names:
        local = os.path.join(ctx.workdir, LICENCES)
        g.download_file(ctx.drive, g.by_name(ctx.asset_items)[LICENCES]["id"],
                        local)
        with open(local, encoding="utf-8") as fh:
            ctx.licences = csv_to_licences(fh.read())
    ctx.used_videos = {str(r.get("source_id")) for r in ctx.licences.values()
                       if r.get("source") == "Pexels"}

    log, retry, filled = [], False, 0
    lines = spec.get("lines", [])
    for n, line in enumerate(lines, 1):
        shot = (line.get("shot") or "").upper()
        if not wants_asset(line):
            continue
        try:
            manual = find_existing(ctx.names, f"{n:02d}")
            if manual:
                name = manual
                ctx.licences.setdefault(manual, {
                    "file": manual, "line": n, "shot": shot,
                    "source": "added by hand", "licence": "check yourself"})
            elif shot == "ART" or (shot == "TEXT" and line.get("art_id")):
                name = get_art(ctx, n, line)
            elif shot in ("STOCK", "SIL"):
                name = get_stock(ctx, n, line)
            else:
                raise Skip(f"{shot} shots are not gathered automatically; "
                           f"put a file named {n:02d}.jpg or {n:02d}.mp4 "
                           "in assets/")
            line["asset_file"] = name
            line.pop("asset_skipped", None)
            filled += 1
        except Exception as exc:  # one bad line must not stop the rest
            line.pop("asset_file", None)
            reason = str(exc) or type(exc).__name__
            if not _definitive(exc):
                retry = True
                reason = f"temporary error, will retry: {type(exc).__name__}"
            line["asset_skipped"] = reason
            log.append(f"line {n} ({shot}): {reason}")
            print(f"[gather] {folder['name']} line {n}: {reason}")

    if retry:
        spec["gather_attempts"] = int(spec.get("gather_attempts", 0)) + 1
    done = not retry or spec.get("gather_attempts", 0) >= MAX_ATTEMPTS
    if done:
        spec.pop("gather_attempts", None)

    g.upload_text(ctx.drive, ctx.assets_id, LICENCES,
                  licences_to_csv(ctx.licences), ctx.workdir,
                  children=ctx.asset_items, mime="text/csv")
    g.upload_text(ctx.drive, folder["id"], "spec.json",
                  _dump(spec), ctx.workdir, children=children,
                  mime="application/json")
    needed = sum(1 for l in lines if wants_asset(l))
    summary = {"short": folder["name"], "filled": filled, "needed": needed,
               "log": log, "done": done}
    if done:
        g.upload_text(ctx.drive, ctx.assets_id, DONE,
                      "\n".join(log) or "all visuals gathered", ctx.workdir,
                      children=ctx.asset_items)
    return summary


def _dump(spec):
    import json
    return json.dumps(spec, indent=1, ensure_ascii=False)


def summary_message(s):
    head = (f"{s['short']}: visuals gathered for {s['filled']} of "
            f"{s['needed']} lines.")
    body = "\n".join("- " + l for l in s["log"])
    tail = (f"Next: lore check, then record {s['short']}.m4a and upload it "
            f"to the {s['short']} folder in Drive. Missing lines will show a "
            "placeholder unless you add a file to assets/ and delete "
            "assets/.done.")
    return "\n".join(p for p in (head, body, tail) if p)


# ---------------------------------------------------------------- main

def main():
    root = g.require_env("DRIVE_ROOT_FOLDER_ID")
    sheet_id = g.require_env("TRACKER_SHEET_ID")
    drive, sheets = g.services()
    ctx = None
    failures = 0
    post_rows = g.read_tab(sheets, sheet_id, "Post log", "A:K")
    for folder in sorted(g.list_folders(drive, root), key=lambda f: f["name"]):
        children = g.list_children(drive, folder["id"])
        assets = next((c for c in children
                       if c["name"] == "assets" and g.is_folder(c)), None)
        asset_children = g.list_children(drive, assets["id"]) if assets else []
        if not needs_gather(children, asset_children):
            continue
        if not lore_checked(post_rows, folder["name"]):
            print(f"[gather] {folder['name']}: waiting for the lore check "
                  "(set its Post log Status to Checked)")
            continue
        print(f"[gather] {folder['name']}: gathering")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                if ctx is None:
                    bank = ArtBank(sheets, sheet_id)
                    ctx = Ctx(drive, bank, tmp, pexels.api_key(),
                              bank.nga_ids())
                ctx.workdir = tmp
                summary = gather_short(ctx, folder, children)
            print(f"[gather] {folder['name']}: {summary['filled']}/"
                  f"{summary['needed']} lines filled")
            if summary["done"]:
                telegram.send_message(summary_message(summary))
        except Exception:
            failures += 1
            traceback.print_exc()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
