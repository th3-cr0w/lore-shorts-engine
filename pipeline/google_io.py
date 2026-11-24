"""Google Drive and Google Sheets helpers.

Login, picked from environment variables (GitHub secrets):
  * Your own Google account (works with a normal @gmail.com Drive):
      GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REFRESH_TOKEN
  * A service account (works when the "Lore Shorts" folder is in a Shared
    Drive, i.e. Google Workspace):
      GOOGLE_SERVICE_ACCOUNT_JSON  (the whole JSON key, pasted as one secret)
If both are set, your own account is used.

Why two ways: Google does not let service accounts own files in a normal
"My Drive", so a service account can read the folder but cannot upload the
finished video there. See SETUP.md, step 4.
"""
import io
import json
import mimetypes
import os

FOLDER_MIME = "application/vnd.google-apps.folder"
SCOPES = ["https://www.googleapis.com/auth/drive",
          "https://www.googleapis.com/auth/spreadsheets"]
FILE_FIELDS = "id, name, mimeType, modifiedTime, size, webViewLink"


# ---------------------------------------------------------------- login

def get_credentials(env=None):
    """Build Google credentials from environment variables."""
    env = os.environ if env is None else env
    oauth = [env.get("GOOGLE_OAUTH_CLIENT_ID"),
             env.get("GOOGLE_OAUTH_CLIENT_SECRET"),
             env.get("GOOGLE_OAUTH_REFRESH_TOKEN")]
    if all(oauth):
        from google.oauth2.credentials import Credentials
        return Credentials(None, refresh_token=oauth[2].strip(),
                           token_uri="https://oauth2.googleapis.com/token",
                           client_id=oauth[0].strip(),
                           client_secret=oauth[1].strip(), scopes=SCOPES)
    raw = env.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        from google.oauth2 import service_account
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON. Paste the "
                "whole key file, from the first { to the last }.") from exc
        return service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES)
    raise RuntimeError(
        "No Google login found. Add the GOOGLE_OAUTH_* secrets or "
        "GOOGLE_SERVICE_ACCOUNT_JSON (see SETUP.md, step 4).")


def services(env=None):
    """Return (drive, sheets) API clients."""
    from googleapiclient.discovery import build
    creds = get_credentials(env)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing setting {name} (see SETUP.md).")
    return value


# ---------------------------------------------------------------- Drive

def list_children(drive, folder_id):
    """Every file and folder directly inside a folder (not in the bin)."""
    items, token = [], None
    while True:
        resp = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=f"nextPageToken, files({FILE_FIELDS})",
            pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        items.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return items


def is_folder(item):
    return item.get("mimeType") == FOLDER_MIME


def list_folders(drive, folder_id):
    return [i for i in list_children(drive, folder_id) if is_folder(i)]


def by_name(items):
    """{name: item}. If two files share a name, the newest wins."""
    out = {}
    for item in sorted(items, key=lambda i: i.get("modifiedTime", "")):
        out[item["name"]] = item
    return out


def ensure_folder(drive, parent_id, name, children=None):
    """Return the id of a sub-folder, creating it if needed."""
    children = list_children(drive, parent_id) if children is None else children
    for item in children:
        if item["name"] == name and is_folder(item):
            return item["id"]
    made = drive.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        fields="id", supportsAllDrives=True).execute()
    return made["id"]


def download_file(drive, file_id, dest):
    """Download a Drive file to a local path."""
    from googleapiclient.http import MediaIoBaseDownload
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with io.FileIO(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=16 << 20)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return dest


def read_json(drive, item):
    """Read a JSON file from Drive. It must be a plain file, not a Google Doc."""
    if item.get("mimeType", "").startswith("application/vnd.google-apps"):
        raise RuntimeError(
            f"{item['name']} is a Google Doc, not a plain .json file. "
            "Save it as a plain file named spec.json.")
    data = drive.files().get_media(fileId=item["id"],
                                   supportsAllDrives=True).execute()
    return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)


def _quota_hint(exc):
    text = str(exc)
    if "storageQuotaExceeded" in text or "do not have storage quota" in text:
        return RuntimeError(
            "Google refused the upload: service accounts cannot save files in "
            "a normal My Drive. Use your own Google account instead "
            "(SETUP.md, step 4A).")
    return None


def upload_file(drive, parent_id, local_path, name=None, children=None,
                mime=None):
    """Upload a file into a folder. If a file with that name is already
    there, replace its contents (same file, same link). Returns the item."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    name = name or os.path.basename(local_path)
    mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
    children = list_children(drive, parent_id) if children is None else children
    existing = next((i for i in children
                     if i["name"] == name and not is_folder(i)), None)
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True,
                            chunksize=16 << 20)
    try:
        if existing:
            return drive.files().update(
                fileId=existing["id"], media_body=media, fields=FILE_FIELDS,
                supportsAllDrives=True).execute()
        return drive.files().create(
            body={"name": name, "parents": [parent_id]}, media_body=media,
            fields=FILE_FIELDS, supportsAllDrives=True).execute()
    except HttpError as exc:
        hint = _quota_hint(exc)
        if hint:
            raise hint from exc
        raise


def upload_text(drive, parent_id, name, text, workdir, children=None,
                mime="text/plain"):
    """Write text to a local file, then upload/replace it on Drive."""
    path = os.path.join(workdir, name.lstrip("."))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return upload_file(drive, parent_id, path, name=name, children=children,
                       mime=mime)


# ---------------------------------------------------------------- Sheets

def col_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def col_index(letter):
    """A -> 0, X -> 23."""
    n = 0
    for ch in letter.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_tab(sheets, sheet_id, tab, cols="A:X"):
    """All rows of a tab as lists of strings (row 1 is the header)."""
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"'{tab}'!{cols}").execute()
    return resp.get("values", [])


def find_row(rows, key, key_col="A"):
    """Sheet row number (1-based) whose key column equals key, or None."""
    idx = col_index(key_col)
    want = str(key).strip().lower()
    for n, row in enumerate(rows[1:], start=2):
        if len(row) > idx and str(row[idx]).strip().lower() == want:
            return n
    return None


def cell(rows, row_number, letter):
    """Value of one cell from read_tab output ('' if empty)."""
    row = rows[row_number - 1] if 0 < row_number <= len(rows) else []
    idx = col_index(letter)
    return row[idx] if len(row) > idx else ""


# Column W of the Post log is a formula for the whole column. Never touch it.
PROTECTED = {"Post log": {"W"}}


def check_protected(tab, updates):
    blocked = PROTECTED.get(tab, set()) & {k.upper() for k in updates}
    if blocked:
        raise ValueError(f"refusing to write protected column(s) {blocked} "
                         f"in {tab}")


def update_cells(sheets, sheet_id, tab, row_number, updates):
    """Write {column letter: value} into one row."""
    check_protected(tab, updates)
    data = [{"range": f"'{tab}'!{letter}{row_number}", "values": [[value]]}
            for letter, value in updates.items()]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=sheet_id,
        body={"valueInputOption": "RAW", "data": data}).execute()


def update_row_by_key(sheets, sheet_id, tab, key, updates, cols="A:X",
                      rows=None):
    """Find the row whose column A is key (a Short ID or Art ID) and update
    it. Returns the row number, or None if the key is not in the sheet."""
    rows = read_tab(sheets, sheet_id, tab, cols) if rows is None else rows
    row_number = find_row(rows, key)
    if row_number:
        update_cells(sheets, sheet_id, tab, row_number, updates)
    return row_number
