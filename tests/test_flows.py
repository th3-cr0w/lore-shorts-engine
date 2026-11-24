"""End-to-end runs of gather and cut against fake Drive, Sheets and web."""
import csv
import io
import json

import pytest
from PIL import Image

from pipeline import art_sources, gather, pexels, telegram, watch_and_cut

ART_HEADER = ["ID", "Artist", "Title", "Year", "Collection", "Rights",
              "Rights check", "Link", "Tags", "Best for", "Note", "Status"]
POST_HEADER = ["Short ID", "Week", "Topic #", "Topic", "Series", "Test variable",
               "Test value", "Visual mix", "Length (s)", "Script doc", "Status",
               "Post date", "YouTube URL", "Instagram URL", "TikTok URL",
               "YT 48h", "YT 7d", "IG 48h", "IG 7d", "TT 48h", "TT 7d",
               "YT avg", "Total 7d", "Notes"]

SPEC = {"id": "W1-1", "topic": "Horus Lupercal", "lines": [
    {"text": "The Emperor's favourite son set the galaxy on fire.",
     "shot": "STOCK", "query": ["burning city night"]},
    {"text": "Horus Lupercal was the first primarch.", "shot": "ART",
     "art_id": "A001"},
    {"text": "So the Emperor gave Horus everything.", "shot": "TEXT",
     "on_screen": "Warmaster"},
    {"text": "Then he was struck by a cursed blade.", "shot": "ART",
     "art_id": "A002"},
    {"text": "The war nearly ended humanity.", "shot": "AI"},
    {"text": "Would you have followed him?", "shot": "ART", "art_id": "A001"},
], "platform_copy": {"youtube": {"title": "Horus", "description": "Lore."},
                     "tiktok": "Horus #warhammer"}}


def art_row(art_id, link, status="Unused", rights_check="OK"):
    return [art_id, "Artist", "Title", "1800", "Met", "Public domain",
            rights_check, link, "", "", "", status]


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "museum.jpg"
    Image.new("RGB", (5000, 3000), (40, 30, 20)).save(path)
    return str(path)


@pytest.fixture
def clip_file(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake mp4")
    return str(path)


def setup_short(drive, spec=SPEC):
    root = drive.add(None, "Lore Shorts", folder=True)
    short = drive.add(root, "W1-1", folder=True)
    drive.add(short, "spec.json", json.dumps(spec))
    return root, short


def test_gather_short(drive, make_sheets, web, image_file, clip_file, tmp_path,
                      monkeypatch):
    sheets = make_sheets({"Art bank": [
        ART_HEADER,
        art_row("A001", "https://www.metmuseum.org/art/collection/search/10"),
        art_row("A002", "https://www.metmuseum.org/art/collection/search/20")]})
    web.json[f"{art_sources.MET_API}/objects/10"] = {
        "isPublicDomain": True, "primaryImage": "https://met/10.jpg"}
    web.json[f"{art_sources.MET_API}/objects/20"] = {
        "isPublicDomain": False, "primaryImage": "https://met/20.jpg"}
    web.files["https://met/10.jpg"] = image_file
    web.json[pexels.SEARCH_URL] = {"videos": [{
        "id": 77, "width": 1080, "height": 1920, "duration": 20,
        "url": "https://www.pexels.com/video/77/",
        "user": {"name": "Ann", "url": "https://www.pexels.com/@ann"},
        "video_files": [{"file_type": "video/mp4", "width": 1080,
                         "height": 1920, "link": "https://pex/77.mp4"}]}]}
    web.files["https://pex/77.mp4"] = clip_file
    messages = []
    monkeypatch.setattr(telegram, "send_message", messages.append)

    _, short = setup_short(drive)
    work = tmp_path / "work"
    work.mkdir()
    bank = gather.ArtBank(None, "sheet")
    ctx = gather.Ctx(None, bank, str(work), "KEY", bank.nga_ids())
    folder = {"id": short, "name": "W1-1"}
    summary = gather.gather_short(ctx, folder, drive.children(short))

    assets = drive.find(short, "assets")["id"]
    names = {c["name"] for c in drive.children(assets)}
    assert names == {"01.mp4", "A001.jpg", "licences.csv", ".done"}
    with Image.open(drive.find(assets, "A001.jpg")["path"]) as im:
        assert max(im.size) == 4000  # shrunk to the cap

    spec = json.loads(drive.read(drive.find(short, "spec.json")["id"]))
    lines = spec["lines"]
    assert lines[0]["asset_file"] == "01.mp4"
    assert lines[1]["asset_file"] == "A001.jpg"
    assert "asset_file" not in lines[2]
    assert "public domain" in lines[3]["asset_skipped"]
    assert "not gathered automatically" in lines[4]["asset_skipped"]
    assert lines[5]["asset_file"] == "A001.jpg"  # same art reused
    assert web.calls.count(("https://met/10.jpg", None, None)) == 1

    lic = {r["file"]: r for r in csv.DictReader(io.StringIO(
        drive.read(drive.find(assets, "licences.csv")["id"]).decode()))}
    assert lic["01.mp4"]["source"] == "Pexels"
    assert "Ann" in lic["01.mp4"]["creator"]
    assert lic["A001.jpg"]["licence"].startswith("CC0")

    assert ("Art bank", 2, {"L": "Downloaded"}) in sheets.writes
    assert all(w[1] != 3 for w in sheets.writes)  # A002 untouched
    assert summary["done"] and summary["filled"] == 3

    # Done shorts are left alone. If .done is deleted, a re-run reuses
    # every file already in assets/ and downloads nothing twice.
    assert not gather.needs_gather(drive.children(short),
                                   drive.children(assets))
    drive.items[drive.find(assets, ".done")["id"]]["parent"] = "bin"
    gather.gather_short(ctx, folder, drive.children(short))
    downloads = [c[0] for c in web.calls if c[0].startswith(("https://met/",
                                                             "https://pex/"))]
    assert downloads == ["https://pex/77.mp4", "https://met/10.jpg"]
    spec2 = json.loads(drive.read(drive.find(short, "spec.json")["id"]))
    assert [l.get("asset_file") for l in spec2["lines"]] == \
        [l.get("asset_file") for l in lines]


def test_gather_retries_after_network_error(drive, make_sheets, web, tmp_path):
    import requests
    make_sheets({"Art bank": [ART_HEADER, art_row(
        "A001", "https://www.metmuseum.org/art/collection/search/10")]})

    def down(_params):
        raise requests.ConnectionError("offline")
    web.json[f"{art_sources.MET_API}/objects/10"] = down
    spec = {"id": "W1-1", "lines": [{"text": "x", "shot": "ART",
                                     "art_id": "A001"}]}
    _, short = setup_short(drive, spec)
    bank = gather.ArtBank(None, "sheet")
    ctx = gather.Ctx(None, bank, str(tmp_path), "", set())
    folder = {"id": short, "name": "W1-1"}
    for attempt in (1, 2):
        s = gather.gather_short(ctx, folder, drive.children(short))
        assert not s["done"]
    s = gather.gather_short(ctx, folder, drive.children(short))
    assert s["done"]  # gives up after 3 tries, so it doesn't loop forever


def test_cut_flow(drive, make_sheets, tmp_path, monkeypatch):
    sheets = make_sheets({"Post log": [
        POST_HEADER, ["W1-1"] + [""] * 9 + ["Checked"] + [""] * 12 + ["old note"]]})
    spec = dict(SPEC)
    spec["lines"] = [dict(SPEC["lines"][0], asset_file="01.mp4"),
                     dict(SPEC["lines"][1], asset_file="A001.jpg"),
                     SPEC["lines"][2],
                     dict(SPEC["lines"][3], asset_skipped="not PD")]
    root, short = setup_short(drive, spec)
    assets = drive.add(short, "assets", folder=True)
    drive.add(assets, "01.mp4", b"clip")
    drive.add(assets, "A001.jpg", b"img")
    drive.add(assets, ".done", b"")
    drive.add(short, "W1-1.m4a", b"voice")

    seen = {}

    def fake_render(spec_path, voice, out, workdir=None):
        with open(spec_path) as fh:
            seen["spec"] = json.load(fh)
        seen["voice"] = open(voice, "rb").read()
        with open(out, "wb") as fh:
            fh.write(b"video")
        return {"passed": False, "duration_s": 31.2,
                "checks": {"vertical_1080x1920": True, "has_audio": True,
                           "voice_matches_script": False,
                           "all_assets_real": False}}
    import engine.render
    monkeypatch.setattr(engine.render, "render", fake_render)
    videos, texts = [], []
    monkeypatch.setattr(telegram, "send_video",
                        lambda path, caption: videos.append(caption) or True)
    monkeypatch.setattr(telegram, "send_message", texts.append)
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", root)
    monkeypatch.setenv("TRACKER_SHEET_ID", "sheet")
    monkeypatch.setattr(watch_and_cut.g, "services", lambda: (None, None))

    out_file = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
    assert watch_and_cut.main(["--check"]) == 0
    assert out_file.read_text() == "needed=true\n"

    assert watch_and_cut.main([]) == 0
    lines = seen["spec"]["lines"]
    assert lines[0]["asset"].endswith("assets/01.mp4")
    assert lines[1]["asset"].endswith("assets/A001.jpg")
    assert "asset" not in lines[3]
    assert seen["voice"] == b"voice"

    assert drive.find(short, "W1-1.mp4") and drive.find(short, "W1-1.qa.json")
    post = drive.read(drive.find(short, "W1-1.post.txt")["id"])
    post = post.decode() if isinstance(post, bytes) else post
    assert "Nothing was posted" in post and "title: Horus" in post
    assert "TIKTOK\n\nHorus #warhammer" in post
    qa = json.loads(drive.read(drive.find(short, "W1-1.qa.json")["id"]))
    assert qa["placeholder_lines"] == [4]

    (tab, row, updates), = sheets.writes
    assert tab == "Post log" and row == 2 and updates["K"] == "Recorded"
    assert updates["X"].startswith("old note\nRendered ")
    assert updates["X"].endswith("QA failed")
    assert "W" not in updates

    assert "QA FAILED: voice_matches_script" in videos[0]
    assert "Placeholder visuals on line(s) 4" in videos[0]
    assert "Nothing was posted" in videos[0]
    assert texts[0].startswith("YOUTUBE") and "title: Horus" in texts[0]
    assert texts[1] == "TIKTOK\n\nHorus #warhammer"

    # Next run: video is newer than the voice, so nothing to do.
    out_file.write_text("")
    watch_and_cut.main(["--check"])
    assert out_file.read_text() == "needed=false\n"


def test_big_video_sends_drive_link(drive, make_sheets, tmp_path, monkeypatch):
    make_sheets({"Post log": [POST_HEADER]})
    root, short = setup_short(drive, {"id": "W1-1", "lines": []})
    assets = drive.add(short, "assets", folder=True)
    drive.add(assets, ".done", b"")
    drive.add(short, "W1-1.mp3", b"voice")
    import engine.render

    def fake_render(spec_path, voice, out, workdir=None):
        open(out, "wb").write(b"v")
        return {"passed": True, "duration_s": 40, "checks": {}}
    monkeypatch.setattr(engine.render, "render", fake_render)
    monkeypatch.setattr(telegram, "send_video", lambda p, c: False)
    texts = []
    monkeypatch.setattr(telegram, "send_message", texts.append)
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", root)
    monkeypatch.setenv("TRACKER_SHEET_ID", "sheet")
    monkeypatch.setattr(watch_and_cut.g, "services", lambda: (None, None))
    assert watch_and_cut.main([]) == 0
    assert "Too big for Telegram" in texts[0]
    assert "https://drive.example/" in texts[0] and "QA passed" in texts[0]


def test_failed_cut_saves_error_and_tells_telegram(drive, make_sheets,
                                                   monkeypatch):
    make_sheets({"Post log": [POST_HEADER]})
    root, short = setup_short(drive, {"id": "W1-1", "lines": []})
    assets = drive.add(short, "assets", folder=True)
    drive.add(assets, ".done", b"")
    drive.add(short, "W1-1.wav", b"voice")
    import engine.render

    def broken(*a, **k):
        raise RuntimeError("ffmpeg exploded")
    monkeypatch.setattr(engine.render, "render", broken)
    texts = []
    monkeypatch.setattr(telegram, "send_message", texts.append)
    monkeypatch.setenv("DRIVE_ROOT_FOLDER_ID", root)
    monkeypatch.setenv("TRACKER_SHEET_ID", "sheet")
    monkeypatch.setattr(watch_and_cut.g, "services", lambda: (None, None))
    assert watch_and_cut.main([]) == 1
    assert drive.find(short, "W1-1.error.txt")
    assert "FAILED" in texts[0] and "ffmpeg exploded" in texts[0]
    assert watch_and_cut.cut_state(
        "W1-1", drive.children(short), drive.children(assets)) == "failed_before"


def test_telegram_errors_hide_the_token(monkeypatch):
    import requests
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    def boom(url, **kw):
        raise requests.ConnectionError(f"cannot reach {url}")
    monkeypatch.setattr(telegram.requests, "post", boom)
    with pytest.raises(RuntimeError) as err:
        telegram.send_message("hi")
    assert "SECRET" not in str(err.value)


def test_telegram_split_text():
    parts = telegram.split_text("a" * 5000 + "\nshort line\n", limit=4096)
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(parts) == "a" * 5000 + "\nshort line\n"
