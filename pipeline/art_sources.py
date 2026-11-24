"""Find a downloadable, openly licensed image for an Art bank link.

Each museum has its own open API. resolve(link) returns a dict:
    {"url": image to download, "licence": short licence text,
     "credit": who to credit, "credit_required": bool, "source": museum}
or raises Skip(reason) when the image is not clearly open or cannot be found.
When in doubt we skip: a skipped line becomes a placeholder, never a risk.
"""
import csv
import html
import re
from urllib.parse import unquote, urlparse, urlunparse

from . import http

CAP = 4000  # longest side we ask for, in pixels

MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"
CLEVELAND_API = "https://openaccess-api.clevelandart.org/api/artworks"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
NASA_ASSET_API = "https://images-api.nasa.gov/asset"
NGA_IMAGES_CSV = ("https://github.com/NationalGalleryOfArt/opendata/raw/"
                  "main/data/published_images.csv")


class Skip(Exception):
    """This artwork cannot be used automatically; str(exc) says why."""


# ---------------------------------------------------------------- links

def classify(link):
    """Work out which collection a link belongs to.
    Returns (kind, key), e.g. ("met", "436535")."""
    link = (link or "").strip()
    if not link:
        return "none", ""
    parsed = urlparse(link if "://" in link else "https://" + link)
    host = parsed.netloc.lower().removeprefix("www.")
    path = unquote(parsed.path)
    fragment = unquote(parsed.fragment)

    if host.endswith("metmuseum.org"):
        m = re.search(r"/art/collection/search/(\d+)", path)
        if m:
            return "met", m.group(1)
        m = re.search(r"/toah/works-of-art/([^/]+)", path)
        if m:
            return "met_accession", m.group(1)
    if host.endswith("clevelandart.org"):
        m = re.search(r"/art/([^/]+)", path)
        if m:
            return "cleveland", m.group(1)
    if host.endswith("nga.gov"):
        m = (re.search(r"art-object-page\.(\d+)", path)
             or re.search(r"/artworks/(\d+)", path))
        if m:
            return "nga", m.group(1)
    if host.endswith("wikimedia.org") or host.endswith("wikipedia.org"):
        if host == "upload.wikimedia.org":
            parts = [p for p in path.split("/") if p]
            name = parts[-2] if "thumb" in parts and len(parts) > 2 else parts[-1]
            return "wikimedia", "File:" + name
        for text in (fragment, path):
            m = re.search(r"(File:[^/?#]+)", text)
            if m:
                return "wikimedia", m.group(1).replace("_", " ")
    if host == "images.nasa.gov":
        m = re.search(r"/details[/-]([^/?#]+)", path)
        if m:
            return "nasa_images", m.group(1)
    if host.endswith("nasa.gov"):
        return "nasa_page", link
    if host.endswith("moma.org"):
        return "moma", link
    if host.endswith("artsandculture.google.com"):
        return "google_arts", link
    if host.endswith("getty.edu"):
        return "getty", link
    return "unknown", link


# ---------------------------------------------------------------- helpers

def pick_size(options, cap=CAP):
    """From [{"url", "width", "height"}], take the largest whose long side
    fits under cap; if all are bigger, the smallest (we shrink it later)."""
    options = [o for o in options if o and o.get("url")]
    if not options:
        return None

    def long_side(o):
        return max(int(o.get("width") or 0), int(o.get("height") or 0))

    fitting = [o for o in options if long_side(o) <= cap]
    if fitting:
        return max(fitting, key=long_side)
    return min(options, key=long_side)


def _strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


# ---------------------------------------------------------------- Met

def _met_result(obj):
    if not obj.get("isPublicDomain"):
        raise Skip("The Met does not mark this object as public domain")
    if not obj.get("primaryImage"):
        raise Skip("The Met has no open image for this object")
    return {"url": obj["primaryImage"], "licence": "CC0 (The Met Open Access)",
            "credit": obj.get("artistDisplayName") or "The Met",
            "credit_required": False, "source": "The Met"}


def met(object_id):
    obj = http.get_json(f"{MET_API}/objects/{object_id}")
    return _met_result(obj)


def met_by_accession(accession):
    found = http.get_json(f"{MET_API}/search", params={"q": accession})
    for object_id in (found.get("objectIDs") or [])[:10]:
        obj = http.get_json(f"{MET_API}/objects/{object_id}")
        if obj.get("accessionNumber", "").strip() == accession.strip():
            return _met_result(obj)
    raise Skip(f"could not find Met accession {accession} in the Met API")


# ---------------------------------------------------------------- Cleveland

def cleveland(key):
    data = http.get_json(f"{CLEVELAND_API}/{key}").get("data") or {}
    if data.get("share_license_status") != "CC0":
        raise Skip("Cleveland Museum of Art does not list this as CC0")
    images = data.get("images") or {}
    choice = pick_size([images.get(k) for k in ("full", "print", "web")])
    if not choice:
        raise Skip("Cleveland Museum of Art has no image for this object")
    creators = data.get("creators") or []
    credit = creators[0].get("description", "") if creators else ""
    return {"url": choice["url"], "licence": "CC0 (Cleveland Museum of Art)",
            "credit": credit or "Cleveland Museum of Art",
            "credit_required": False, "source": "Cleveland Museum of Art"}


# ---------------------------------------------------------------- NGA

_nga_rows = None  # object id -> list of image rows, loaded once per run


def _load_nga(wanted_ids):
    """Read NGA's open data image list, keeping only the objects we need."""
    global _nga_rows
    if _nga_rows is None:
        _nga_rows = {}
        reader = csv.DictReader(http.iter_lines(NGA_IMAGES_CSV))
        for row in reader:
            oid = (row.get("depictstmsobjectid") or "").strip()
            if oid in wanted_ids:
                _nga_rows.setdefault(oid, []).append(row)
    return _nga_rows


def nga(object_id, wanted_ids=None):
    try:
        rows = _load_nga(set(wanted_ids or []) | {object_id}).get(object_id)
    except Exception as exc:
        raise Skip(f"could not read NGA open data ({type(exc).__name__})")
    if not rows:
        raise Skip("NGA open data has no image for this object")
    rows.sort(key=lambda r: (r.get("viewtype") != "primary",
                             r.get("sequence") or ""))
    row = rows[0]
    # A pixel limit means NGA restricts the image: not open access.
    if (row.get("maxpixels") or "").strip():
        raise Skip("NGA limits this image's size (not open access)")
    if not row.get("iiifurl"):
        raise Skip("NGA open data row has no image address")
    w, h = int(row.get("width") or 0), int(row.get("height") or 0)
    size = "full" if 0 < max(w, h) <= CAP else f"!{CAP},{CAP}"
    return {"url": f"{row['iiifurl'].rstrip('/')}/full/{size}/0/default.jpg",
            "licence": "CC0 (National Gallery of Art Open Access)",
            "credit": "National Gallery of Art, Washington",
            "credit_required": False, "source": "National Gallery of Art"}


# ---------------------------------------------------------------- Wikimedia

def wikimedia_licence(short, code):
    """'open' (no credit needed), 'credit' (CC BY / BY-SA) or None (skip)."""
    short, code = short.lower().strip(), code.lower().strip()
    if (short.startswith("public domain") or short.startswith("pd")
            or "cc0" in short or code in ("pd", "cc0", "cc-zero")
            or code.startswith("pd-") or short == "no restrictions"):
        return "open"
    if re.match(r"cc[ -]by(-sa)?([ -]\d|$)", short) or \
            re.match(r"cc-by(-sa)?-\d", code):
        return "credit"
    return None


def wikimedia(title):
    resp = http.get_json(COMMONS_API, params={
        "action": "query", "titles": title, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": CAP,
        "format": "json", "formatversion": 2})
    pages = (resp.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing") or not pages[0].get("imageinfo"):
        raise Skip("file is not on Wikimedia Commons (it may be a local "
                   "Wikipedia file, which is often not free)")
    info = pages[0]["imageinfo"][0]
    if info.get("mime") not in ("image/jpeg", "image/png", "image/tiff",
                                "image/webp"):
        raise Skip(f"not a photo-type image ({info.get('mime')})")
    meta = info.get("extmetadata") or {}
    short = _strip_tags((meta.get("LicenseShortName") or {}).get("value", ""))
    code = _strip_tags((meta.get("License") or {}).get("value", ""))
    artist = _strip_tags((meta.get("Artist") or {}).get("value", ""))
    nonfree = str((meta.get("NonFree") or {}).get("value", "")).lower()
    verdict = None if nonfree in ("true", "1") else wikimedia_licence(short, code)
    if verdict is None:
        raise Skip(f"licence not clearly free: {short or 'unknown'}")
    needs_credit = verdict == "credit"
    return {"url": info.get("thumburl") or info["url"],
            "licence": short or code, "credit": artist or "Wikimedia Commons",
            "credit_required": needs_credit, "source": "Wikimedia Commons"}


# ---------------------------------------------------------------- NASA

NASA_LICENCE = ("NASA media (generally not copyrighted; check the credit "
                "line for partner images)")


def nasa_images(nasa_id):
    resp = http.get_json(f"{NASA_ASSET_API}/{nasa_id}")
    hrefs = [i.get("href", "") for i in
             (resp.get("collection") or {}).get("items", [])]
    for suffix in ("~orig.jpg", "~large.jpg", "~orig.png", "~medium.jpg"):
        for href in hrefs:
            if href.lower().endswith(suffix):
                return {"url": href.replace("http://", "https://", 1),
                        "licence": NASA_LICENCE, "credit": "NASA",
                        "credit_required": True, "source": "NASA"}
    raise Skip("NASA image library has no JPEG/PNG for this item")


def nasa_page(url):
    page = http.get_text(url)
    m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']'
                   r'([^"\']+)', page)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                      r'property=["\']og:image["\']', page))
    if not m:
        raise Skip("could not find the main image on the NASA page")
    image = html.unescape(m.group(1))
    # The page shares a resized copy; without the size settings the image
    # server usually gives the original. gather tries this first.
    full = urlunparse(urlparse(image)._replace(query=""))
    return {"url": full, "fallback_url": image, "licence": NASA_LICENCE,
            "credit": "NASA", "credit_required": True, "source": "NASA"}


# ---------------------------------------------------------------- entry

def resolve(link, nga_ids=None):
    """Turn an Art bank link into download details, or raise Skip."""
    kind, key = classify(link)
    if kind == "met":
        return met(key)
    if kind == "met_accession":
        return met_by_accession(key)
    if kind == "cleveland":
        return cleveland(key)
    if kind == "nga":
        return nga(key, nga_ids)
    if kind == "wikimedia":
        return wikimedia(key)
    if kind == "nasa_images":
        return nasa_images(key)
    if kind == "nasa_page":
        return nasa_page(key)
    if kind == "moma":
        raise Skip("MoMA works are not open access; find an open copy")
    if kind == "google_arts":
        raise Skip("Google Arts & Culture has no open download; use the same "
                   "work's Wikimedia Commons or museum page instead")
    if kind == "getty":
        raise Skip("Getty links are not downloaded automatically; use the "
                   "work's Wikimedia Commons page instead")
    if kind == "none":
        raise Skip("no link in the Art bank")
    raise Skip(f"unknown collection for link {link}")
