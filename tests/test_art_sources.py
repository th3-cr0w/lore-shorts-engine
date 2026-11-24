"""Art bank link -> open-API request -> image, for each collection."""
import pytest

from pipeline import art_sources as a
from pipeline.art_sources import Skip

MET = a.MET_API
CMA = a.CLEVELAND_API


@pytest.mark.parametrize("link, expected", [
    ("https://www.metmuseum.org/art/collection/search/436535",
     ("met", "436535")),
    ("https://www.metmuseum.org/art/collection/search/436535?searchField=All",
     ("met", "436535")),
    ("https://www.metmuseum.org/toah/works-of-art/29.100.5/",
     ("met_accession", "29.100.5")),
    ("https://www.clevelandart.org/art/1915.534", ("cleveland", "1915.534")),
    ("https://www.clevelandart.org/art/135382", ("cleveland", "135382")),
    ("https://www.nga.gov/collection/art-object-page.46471.html",
     ("nga", "46471")),
    ("https://www.nga.gov/artworks/46471-the-voyage-of-life", ("nga", "46471")),
    ("https://commons.wikimedia.org/wiki/File:John_Martin_-_Pandemonium.jpg",
     ("wikimedia", "File:John Martin - Pandemonium.jpg")),
    ("https://en.wikipedia.org/wiki/File:The_Fall_of_the_Rebel_Angels.jpg",
     ("wikimedia", "File:The Fall of the Rebel Angels.jpg")),
    ("https://en.wikipedia.org/wiki/Pandemonium#/media/File:Martin_Pan.jpg",
     ("wikimedia", "File:Martin Pan.jpg")),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X_y.jpg/800px-X_y.jpg",
     ("wikimedia", "File:X_y.jpg")),
    ("https://images.nasa.gov/details/PIA12348", ("nasa_images", "PIA12348")),
    ("https://www.moma.org/collection/works/79802",
     ("moma", "https://www.moma.org/collection/works/79802")),
    ("https://artsandculture.google.com/asset/x/abc",
     ("google_arts", "https://artsandculture.google.com/asset/x/abc")),
    ("http://www.getty.edu/cona/CONAFullSubject.aspx?subid=700000",
     ("getty", "http://www.getty.edu/cona/CONAFullSubject.aspx?subid=700000")),
    ("", ("none", "")),
])
def test_classify(link, expected):
    assert a.classify(link) == expected


def test_classify_nasa_science_page():
    kind, _ = a.classify("https://science.nasa.gov/image-article/pillars/")
    assert kind == "nasa_page"


# ---- The Met

def test_met_public_domain_uses_primary_image(web):
    web.json[f"{MET}/objects/436535"] = {
        "isPublicDomain": True, "primaryImage": "https://images.met/full.jpg",
        "artistDisplayName": "Vincent van Gogh"}
    got = a.resolve("https://www.metmuseum.org/art/collection/search/436535")
    assert got["url"] == "https://images.met/full.jpg"
    assert "CC0" in got["licence"]
    assert got["credit"] == "Vincent van Gogh"


def test_met_not_public_domain_is_skipped(web):
    web.json[f"{MET}/objects/1"] = {"isPublicDomain": False,
                                    "primaryImage": "https://x/y.jpg"}
    with pytest.raises(Skip, match="not mark this object as public domain"):
        a.resolve("https://www.metmuseum.org/art/collection/search/1")


def test_met_public_domain_without_image_is_skipped(web):
    web.json[f"{MET}/objects/2"] = {"isPublicDomain": True, "primaryImage": ""}
    with pytest.raises(Skip, match="no open image"):
        a.resolve("https://www.metmuseum.org/art/collection/search/2")


def test_met_toah_accession_lookup(web):
    web.json[(f"{MET}/search", frozenset({("q", "29.100.5")}))] = {
        "total": 2, "objectIDs": [11, 12]}
    web.json[f"{MET}/objects/11"] = {"accessionNumber": "29.100.55",
                                     "isPublicDomain": True,
                                     "primaryImage": "https://wrong.jpg"}
    web.json[f"{MET}/objects/12"] = {"accessionNumber": "29.100.5",
                                     "isPublicDomain": True,
                                     "primaryImage": "https://right.jpg"}
    got = a.resolve("https://www.metmuseum.org/toah/works-of-art/29.100.5/")
    assert got["url"] == "https://right.jpg"


# ---- Cleveland

def _cma(status, images):
    return {"data": {"share_license_status": status, "images": images,
                     "creators": [{"description": "Thomas Cole (American)"}]}}


def test_cleveland_cc0_picks_largest_under_cap(web):
    web.json[f"{CMA}/1915.534"] = _cma("CC0", {
        "web": {"url": "https://c/web.jpg", "width": 900, "height": 1200},
        "print": {"url": "https://c/print.jpg", "width": 2700, "height": 3400},
        "full": {"url": "https://c/full.tif", "width": 7000, "height": 9000}})
    got = a.resolve("https://www.clevelandart.org/art/1915.534")
    assert got["url"] == "https://c/print.jpg"
    assert got["credit"].startswith("Thomas Cole")


def test_cleveland_not_cc0_is_skipped(web):
    web.json[f"{CMA}/2000.1"] = _cma("Copyrighted", {
        "web": {"url": "https://c/web.jpg", "width": 900, "height": 1200}})
    with pytest.raises(Skip, match="CC0"):
        a.resolve("https://www.clevelandart.org/art/2000.1")


def test_pick_size_all_too_big_takes_smallest():
    got = a.pick_size([{"url": "a", "width": 9000, "height": 5000},
                       {"url": "b", "width": 6000, "height": 4500}])
    assert got["url"] == "b"


# ---- NGA

NGA_HEADER = ("uuid,iiifurl,iiifthumburl,viewtype,sequence,width,height,"
              "maxpixels,created,modified,depictstmsobjectid,assistivetext")


def test_nga_open_image_from_open_data(web):
    web.lines[a.NGA_IMAGES_CSV] = [
        NGA_HEADER,
        "u1,https://api.nga.gov/iiif/u1,t,alternate,1,3000,4000,,,,46471,",
        "u2,https://api.nga.gov/iiif/u2,t,primary,0,5000,6000,,,,46471,",
        "u3,https://api.nga.gov/iiif/u3,t,primary,0,100,100,,,,999,"]
    got = a.resolve("https://www.nga.gov/collection/art-object-page.46471.html")
    assert got["url"] == "https://api.nga.gov/iiif/u2/full/!4000,4000/0/default.jpg"


def test_nga_restricted_image_is_skipped(web):
    web.lines[a.NGA_IMAGES_CSV] = [
        NGA_HEADER, "u9,https://api.nga.gov/iiif/u9,t,primary,0,800,600,640,,,77,"]
    with pytest.raises(Skip, match="not open access"):
        a.resolve("https://www.nga.gov/artworks/77-something")


def test_nga_missing_object_is_skipped(web):
    web.lines[a.NGA_IMAGES_CSV] = [NGA_HEADER]
    with pytest.raises(Skip, match="no image"):
        a.resolve("https://www.nga.gov/artworks/5-x")


# ---- Wikimedia Commons

def _commons(licence_short, licence_code, mime="image/jpeg", missing=False,
             nonfree=None):
    if missing:
        return {"query": {"pages": [{"title": "File:X.jpg", "missing": True}]}}
    meta = {"LicenseShortName": {"value": licence_short},
            "License": {"value": licence_code},
            "Artist": {"value": '<a href="//x">John Martin</a>'}}
    if nonfree:
        meta["NonFree"] = {"value": nonfree}
    return {"query": {"pages": [{"title": "File:X.jpg", "imageinfo": [{
        "url": "https://upload/X.jpg", "thumburl": "https://upload/4000px-X.jpg",
        "width": 6000, "height": 4000, "mime": mime, "extmetadata": meta}]}]}}


def test_wikimedia_public_domain(web):
    web.json[a.COMMONS_API] = _commons("Public domain", "pd")
    got = a.resolve("https://commons.wikimedia.org/wiki/File:X.jpg")
    assert got["url"] == "https://upload/4000px-X.jpg"
    assert got["credit"] == "John Martin"
    assert got["credit_required"] is False
    params = web.calls[0][1]
    assert params["titles"] == "File:X.jpg" and params["prop"] == "imageinfo"


def test_wikimedia_cc_by_sa_needs_credit(web):
    web.json[a.COMMONS_API] = _commons("CC BY-SA 4.0", "cc-by-sa-4.0")
    got = a.resolve("https://en.wikipedia.org/wiki/File:X.jpg")
    assert got["credit_required"] is True


@pytest.mark.parametrize("short, code, nonfree", [
    ("Fair use", "", None), ("GFDL", "gfdl", None),
    ("CC BY-NC 2.0", "cc-by-nc-2.0", None), ("Public domain", "pd", "true")])
def test_wikimedia_unclear_licences_are_skipped(web, short, code, nonfree):
    web.json[a.COMMONS_API] = _commons(short, code, nonfree=nonfree)
    with pytest.raises(Skip):
        a.resolve("https://commons.wikimedia.org/wiki/File:X.jpg")


def test_wikimedia_local_file_is_skipped(web):
    web.json[a.COMMONS_API] = _commons("", "", missing=True)
    with pytest.raises(Skip, match="not on Wikimedia Commons"):
        a.resolve("https://en.wikipedia.org/wiki/File:X.jpg")


def test_wikimedia_svg_is_skipped(web):
    web.json[a.COMMONS_API] = _commons("Public domain", "pd", mime="image/svg+xml")
    with pytest.raises(Skip, match="photo-type"):
        a.resolve("https://commons.wikimedia.org/wiki/File:X.svg")


# ---- NASA

def test_nasa_image_library_prefers_original(web):
    web.json[f"{a.NASA_ASSET_API}/PIA12348"] = {"collection": {"items": [
        {"href": "http://images-assets.nasa.gov/image/PIA12348/PIA12348~thumb.jpg"},
        {"href": "http://images-assets.nasa.gov/image/PIA12348/PIA12348~orig.jpg"},
        {"href": "http://images-assets.nasa.gov/image/PIA12348/metadata.json"}]}}
    got = a.resolve("https://images.nasa.gov/details/PIA12348")
    assert got["url"] == ("https://images-assets.nasa.gov/image/PIA12348/"
                          "PIA12348~orig.jpg")


def test_nasa_science_page_uses_og_image(web):
    url = "https://science.nasa.gov/image-article/pillars/"
    web.text[url] = ('<html><head><meta property="og:image" '
                     'content="https://assets.science.nasa.gov/p.jpg?w=1200&amp;h=630">'
                     '</head></html>')
    got = a.resolve(url)
    assert got["url"] == "https://assets.science.nasa.gov/p.jpg"
    assert got["fallback_url"] == "https://assets.science.nasa.gov/p.jpg?w=1200&h=630"


# ---- never downloaded automatically

@pytest.mark.parametrize("link", [
    "https://www.moma.org/collection/works/79802",
    "https://artsandculture.google.com/asset/the-abyss/abc",
    "http://www.getty.edu/cona/CONAFullSubject.aspx?subid=1",
    "https://example.com/some-image.jpg",
    ""])
def test_uncertain_sources_are_skipped(web, link):
    with pytest.raises(Skip):
        a.resolve(link)
    assert web.calls == []  # and no request was made
