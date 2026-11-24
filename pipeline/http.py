"""Small web helpers shared by the pipeline: polite retries and timeouts.

Tests replace get_json / get_text / download with fakes, so no real
network call is ever made while testing.
"""
import os
import time

import requests

# Museums and Wikimedia ask automated clients to identify themselves with a
# contact address. On GitHub Actions that is the repo's own page
# (GITHUB_REPOSITORY is set automatically, e.g. "name/lore-shorts-engine").
_REPO = os.environ.get("GITHUB_REPOSITORY", "")
USER_AGENT = ("LoreShortsEngine/1.0 (open-source video pipeline"
              + (f"; https://github.com/{_REPO}" if _REPO else "")
              + ") python-requests")
TIMEOUT = 60
RETRY_STATUS = {429, 500, 502, 503, 504}


def get(url, params=None, headers=None, stream=False, tries=3):
    """GET with a few retries for busy servers. Raises on a final failure."""
    all_headers = {"User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, params=params, headers=all_headers,
                                timeout=TIMEOUT, stream=stream)
            if resp.status_code in RETRY_STATUS and attempt < tries:
                time.sleep(3 * attempt)
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt == tries:
                raise
            time.sleep(3 * attempt)
    raise RuntimeError("unreachable")


def get_json(url, params=None, headers=None):
    return get(url, params=params, headers=headers).json()


def get_text(url, params=None, headers=None):
    return get(url, params=params, headers=headers).text


def download(url, dest, headers=None, max_mb=400):
    """Stream a file to disk. Stops if it is unexpectedly huge."""
    resp = get(url, headers=headers, stream=True)
    size = 0
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            size += len(chunk)
            if size > max_mb * (1 << 20):
                raise ValueError(f"file larger than {max_mb} MB: {url}")
            fh.write(chunk)
    return dest


def iter_lines(url):
    """Stream a large text file line by line (used for NGA's open data CSV)."""
    resp = get(url, stream=True)
    resp.encoding = resp.encoding or "utf-8"
    return resp.iter_lines(decode_unicode=True)
