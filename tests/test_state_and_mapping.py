"""Which shorts need gathering or cutting, and spec asset mapping."""
from pipeline import gather, google_io as g
from pipeline.watch_and_cut import cut_state, find_voice, map_assets


def f(name, t="2026-11-24T10:00:00.000Z", folder=False):
    return {"id": name, "name": name, "modifiedTime": t,
            "mimeType": g.FOLDER_MIME if folder else "application/json"}


DONE = [f(".done"), f("A001.jpg")]


# ---- gather

def test_needs_gather_when_spec_and_no_done():
    assert gather.needs_gather([f("spec.json")], [])
    assert gather.needs_gather([f("spec.json"), f("assets", folder=True)],
                               [f("01.mp4")])


def test_no_gather_without_spec_or_when_done():
    assert not gather.needs_gather([f("notes.txt")], [])
    assert not gather.needs_gather([f("spec.json")], DONE)


# ---- cut

def test_cut_waits_for_spec_voice_and_assets():
    assert cut_state("W1-1", []) == "no_spec"
    assert cut_state("W1-1", [f("spec.json")]) == "waiting_voice"
    kids = [f("spec.json"), f("W1-1.m4a")]
    assert cut_state("W1-1", kids) == "check_assets"
    assert cut_state("W1-1", kids, []) == "waiting_assets"
    assert cut_state("W1-1", kids, DONE) == "ready"


def test_voice_name_rules():
    kids = [f("spec.json"), f("w1-1.MP3"), f("W1-10.m4a"), f("W1-1.txt")]
    assert find_voice("W1-1", kids)["name"] == "w1-1.MP3"
    assert find_voice("W1-2", kids) is None


def test_cut_done_when_video_newer_than_voice():
    kids = [f("spec.json"), f("W1-1.wav", "2026-11-24T10:00:00.000Z"),
            f("W1-1.mp4", "2026-11-24T11:00:00.000Z")]
    assert cut_state("W1-1", kids, DONE) == "done"


def test_new_voice_recording_triggers_recut():
    kids = [f("spec.json"), f("W1-1.mp4", "2026-11-24T11:00:00.000Z"),
            f("W1-1.m4a", "2026-11-24T12:00:00.000Z")]
    assert cut_state("W1-1", kids, DONE) == "ready"


def test_failed_cut_waits_until_error_removed_or_new_voice():
    kids = [f("spec.json"), f("W1-1.m4a", "2026-11-24T10:00:00.000Z"),
            f("W1-1.error.txt", "2026-11-24T10:30:00.000Z")]
    assert cut_state("W1-1", kids, DONE) == "failed_before"
    kids[1] = f("W1-1.m4a", "2026-11-24T11:00:00.000Z")
    assert cut_state("W1-1", kids, DONE) == "ready"


# ---- mapping

def test_map_assets(tmp_path):
    (tmp_path / "A001.jpg").write_bytes(b"x")
    (tmp_path / "01.mp4").write_bytes(b"x")
    spec = {"lines": [
        {"text": "a", "shot": "STOCK", "asset_file": "01.mp4"},
        {"text": "b", "shot": "ART", "art_id": "A001", "asset_file": "A001.jpg"},
        {"text": "c", "shot": "TEXT", "on_screen": "Warmaster"},
        {"text": "d", "shot": "SIL", "asset_skipped": "no clip"},
        {"text": "e", "shot": "STOCK", "asset_file": "05.mp4"},  # not downloaded
    ]}
    placeholders = map_assets(spec, str(tmp_path))
    lines = spec["lines"]
    assert lines[0]["asset"] == str(tmp_path / "01.mp4")
    assert lines[1]["asset"] == str(tmp_path / "A001.jpg")
    assert "asset" not in lines[2] and "asset" not in lines[3]
    assert "asset" not in lines[4]
    assert placeholders == [4, 5]


def test_engine_keeps_mapped_art_asset(tmp_path):
    """engine.render.resolve_asset must not override a mapped asset."""
    from engine.render import resolve_asset
    line = {"shot": "ART", "art_id": "TEST1", "asset": "/tmp/x/A001.jpg"}
    resolve_asset(line)
    assert line["asset"] == "/tmp/x/A001.jpg"


# ---- google_io helpers

def test_column_letters():
    assert g.col_letter(0) == "A" and g.col_letter(23) == "X"
    assert g.col_letter(26) == "AA" and g.col_index("X") == 23


def test_find_row_and_cell():
    rows = [["Short ID", "Week"], ["W1-1", "1"], ["w1-2", "1"]]
    assert g.find_row(rows, "W1-2") == 3
    assert g.find_row(rows, "W9-9") is None
    assert g.cell(rows, 2, "B") == "1" and g.cell(rows, 2, "X") == ""


def test_post_log_formula_column_is_protected():
    import pytest
    from unittest.mock import MagicMock
    sheets = MagicMock()
    with pytest.raises(ValueError):
        g.update_cells(sheets, "sid", "Post log", 2, {"W": "1"})
    sheets.spreadsheets.assert_not_called()
    g.update_cells(sheets, "sid", "Post log", 2, {"K": "Recorded"})
    body = sheets.spreadsheets().values().batchUpdate.call_args.kwargs["body"]
    assert body["data"] == [{"range": "'Post log'!K2", "values": [["Recorded"]]}]


def test_list_children_follows_pages():
    from unittest.mock import MagicMock
    drive = MagicMock()
    drive.files().list().execute.side_effect = [
        {"files": [{"name": "a"}], "nextPageToken": "t"},
        {"files": [{"name": "b"}]}]
    assert [i["name"] for i in g.list_children(drive, "F")] == ["a", "b"]
    kwargs = drive.files().list.call_args.kwargs
    assert kwargs["q"] == "'F' in parents and trashed = false"
    assert kwargs["supportsAllDrives"] is True


def test_credentials_need_some_login():
    import pytest
    with pytest.raises(RuntimeError, match="No Google login"):
        g.get_credentials({})
    with pytest.raises(RuntimeError, match="not valid JSON"):
        g.get_credentials({"GOOGLE_SERVICE_ACCOUNT_JSON": "{oops"})


def test_oauth_login_preferred():
    creds = g.get_credentials({"GOOGLE_OAUTH_CLIENT_ID": "id",
                               "GOOGLE_OAUTH_CLIENT_SECRET": "s",
                               "GOOGLE_OAUTH_REFRESH_TOKEN": "r",
                               "GOOGLE_SERVICE_ACCOUNT_JSON": "{oops"})
    assert creds.refresh_token == "r"


def test_upload_creates_or_replaces(tmp_path):
    from unittest.mock import MagicMock
    path = tmp_path / "W1-1.mp4"
    path.write_bytes(b"v")
    drive = MagicMock()
    g.upload_file(drive, "F", str(path), children=[])
    kwargs = drive.files().create.call_args.kwargs
    assert kwargs["body"] == {"name": "W1-1.mp4", "parents": ["F"]}
    g.upload_file(drive, "F", str(path),
                  children=[{"id": "old", "name": "W1-1.mp4",
                             "mimeType": "video/mp4"}])
    assert drive.files().update.call_args.kwargs["fileId"] == "old"


def test_service_account_quota_error_explained(tmp_path):
    import pytest
    from unittest.mock import MagicMock
    from googleapiclient.errors import HttpError
    path = tmp_path / "a.csv"
    path.write_text("x")
    drive = MagicMock()
    resp = MagicMock(status=403, reason="Forbidden")
    drive.files().create().execute.side_effect = HttpError(
        resp, b'{"error": {"errors": [{"reason": "storageQuotaExceeded"}],'
              b'"message": "Service Accounts do not have storage quota."}}')
    with pytest.raises(RuntimeError, match="step 4A"):
        g.upload_file(drive, "F", str(path), children=[])


def test_gather_waits_for_lore_check():
    rows = [["Short ID"] + [""] * 10,
            ["W1-1"] + [""] * 9 + ["Scripted"],
            ["W1-2"] + [""] * 9 + ["Checked"],
            ["W1-3"] + [""] * 9 + ["Posted"]]
    assert not gather.lore_checked(rows, "W1-1")
    assert gather.lore_checked(rows, "W1-2")
    assert gather.lore_checked(rows, "w1-3")
    assert not gather.lore_checked(rows, "W9-9")


def test_text_lines_with_art_get_a_background():
    assert not gather.wants_asset({"shot": "TEXT", "on_screen": "Warmaster"})
    assert gather.wants_asset({"shot": "TEXT", "art_id": "A048"})
    assert gather.wants_asset({"shot": "ART", "art_id": "A007"})
    assert gather.wants_asset({"shot": "STOCK"})


def test_expired_login_gives_clear_message():
    import pytest
    from google.auth.exceptions import RefreshError

    class Expired:
        def refresh(self, request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(RuntimeError) as err:
        g.check_login(Expired())
    msg = str(err.value)
    assert "GOOGLE_OAUTH_REFRESH_TOKEN" in msg and "7 days" in msg
    assert "invalid_grant" in msg


def test_working_login_passes_through():
    class Fine:
        refreshed = False

        def refresh(self, request):
            self.refreshed = True

    creds = Fine()
    assert g.check_login(creds) is creds and creds.refreshed
