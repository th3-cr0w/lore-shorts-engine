"""Shared test helpers: a fake web and a fake Google Drive / Sheets.

No test ever talks to a real service."""
import os
import shutil

import pytest

from pipeline import art_sources, google_io as g, http


class FakeWeb:
    """Answers pipeline.http calls from a dict of canned responses.
    Keys are URLs; for JSON calls a key may also be (url, frozenset(params))."""

    def __init__(self):
        self.json, self.text, self.files, self.lines = {}, {}, {}, {}
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        if params is not None:
            key = (url, frozenset((k, str(v)) for k, v in params.items()))
            if key in self.json:
                value = self.json[key]
                return value(params) if callable(value) else value
        if url not in self.json:
            raise AssertionError(f"unexpected JSON request: {url} {params}")
        value = self.json[url]
        return value(params) if callable(value) else value

    def get_text(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self.text[url]

    def download(self, url, dest, headers=None, max_mb=400):
        self.calls.append((url, None, headers))
        if url not in self.files:
            raise AssertionError(f"unexpected download: {url}")
        shutil.copyfile(self.files[url], dest)
        return dest

    def iter_lines(self, url):
        self.calls.append((url, None, None))
        return iter(self.lines[url])


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(http, "get_json", fake.get_json)
    monkeypatch.setattr(http, "get_text", fake.get_text)
    monkeypatch.setattr(http, "download", fake.download)
    monkeypatch.setattr(http, "iter_lines", fake.iter_lines)
    monkeypatch.setattr(art_sources, "_nga_rows", None)
    return fake


class FakeDrive:
    """In-memory Drive. Items: id -> dict(name, parent, mimeType,
    modifiedTime, content path or bytes)."""

    def __init__(self, tmpdir):
        self.tmp = tmpdir
        self.items = {}
        self.clock = 0
        self.uploads = []

    def _stamp(self):
        self.clock += 1
        return f"2026-11-24T10:{self.clock // 60:02d}:{self.clock % 60:02d}.000Z"

    def add(self, parent, name, data=b"", folder=False, stamp=None):
        fid = f"id{len(self.items) + 1}"
        path = None
        if not folder:
            path = os.path.join(self.tmp, f"drive_{fid}")
            with open(path, "wb") as fh:
                fh.write(data if isinstance(data, bytes) else data.encode())
        self.items[fid] = {
            "id": fid, "name": name, "parent": parent, "path": path,
            "mimeType": g.FOLDER_MIME if folder else "application/octet-stream",
            "modifiedTime": stamp or self._stamp(),
            "webViewLink": f"https://drive.example/{fid}"}
        return fid

    def children(self, folder_id):
        return [{k: v for k, v in i.items() if k not in ("parent", "path")}
                for i in self.items.values() if i["parent"] == folder_id]

    def read(self, fid):
        with open(self.items[fid]["path"], "rb") as fh:
            return fh.read()

    def find(self, parent, name):
        for i in self.items.values():
            if i["parent"] == parent and i["name"] == name:
                return i
        return None

    # --- stand-ins for pipeline.google_io functions
    def list_children(self, _drive, folder_id):
        return self.children(folder_id)

    def list_folders(self, _drive, folder_id):
        return [c for c in self.children(folder_id) if g.is_folder(c)]

    def ensure_folder(self, _drive, parent, name, children=None):
        found = self.find(parent, name)
        return found["id"] if found else self.add(parent, name, folder=True)

    def download_file(self, _drive, fid, dest):
        shutil.copyfile(self.items[fid]["path"], dest)
        return dest

    def read_json(self, _drive, item):
        import json
        return json.loads(self.read(item["id"]).decode())

    def upload_file(self, _drive, parent, local, name=None, children=None,
                    mime=None):
        name = name or os.path.basename(local)
        with open(local, "rb") as fh:
            data = fh.read()
        self.uploads.append(name)
        found = self.find(parent, name)
        if found:
            with open(found["path"], "wb") as fh:
                fh.write(data)
            found["modifiedTime"] = self._stamp()
            return {k: v for k, v in found.items() if k != "path"}
        fid = self.add(parent, name, data)
        return {k: v for k, v in self.items[fid].items() if k != "path"}

    def upload_text(self, _drive, parent, name, text, workdir, children=None,
                    mime=None):
        path = os.path.join(workdir, "up_" + name.lstrip("."))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.upload_file(None, parent, path, name=name)


@pytest.fixture
def drive(tmp_path, monkeypatch):
    fake = FakeDrive(str(tmp_path))
    for name in ("list_children", "list_folders", "ensure_folder",
                 "download_file", "read_json", "upload_file", "upload_text"):
        monkeypatch.setattr(g, name, getattr(fake, name))
    return fake


class FakeSheets:
    """Stand-in for pipeline.google_io's read_tab / update_cells."""

    def __init__(self, tabs):
        self.tabs = tabs  # tab name -> list of rows
        self.writes = []

    def read_tab(self, _sheets, _sid, tab, cols="A:X"):
        return [list(r) for r in self.tabs[tab]]

    def update_cells(self, _sheets, _sid, tab, row, updates):
        g.check_protected(tab, updates)
        self.writes.append((tab, row, dict(updates)))
        line = self.tabs[tab][row - 1]
        for letter, value in updates.items():
            idx = g.col_index(letter)
            line.extend([""] * (idx + 1 - len(line)))
            line[idx] = value


@pytest.fixture
def make_sheets(monkeypatch):
    def factory(tabs):
        fake = FakeSheets(tabs)
        monkeypatch.setattr(g, "read_tab", fake.read_tab)
        monkeypatch.setattr(g, "update_cells", fake.update_cells)
        return fake
    return factory

